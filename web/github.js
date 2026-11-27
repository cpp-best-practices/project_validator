// A public GitHub repository, read into the page (upstream #127): the ref resolved to a commit, its whole tree listed,
// and every file fetched from raw.githubusercontent.com, with retries and jsDelivr as the fallback (the archives
// GitHub serves refuse a page's requests). Two API calls a run: 60 an hour without a token, 5000 with one.
"use strict";
/* exported parseRepository, readRepository */

/**
 * @typedef {{ owner: string, name: string, ref: string }} Repository
 * @typedef {{ path: string, size: number, bytes: ArrayBuffer | null }} ProjectFile
 * @typedef {{ path: string, type: string, mode: string, size: number }} TreeEntry
 */

// Files larger than this are not fetched: their size alone is given, as large-files asks for nothing else.
const MOST_FETCHED = 1024 * 1024;
const IN_FLIGHT = 32;
const TRIES = 3;

/**
 * @param {string | undefined} text
 * @returns {Repository | null}
 */
function parseRepository(text) {
  // "owner/name@ref" (the ref may hold slashes: a branch, a tag, a commit); the default branch when none is given.
  const written = (text || "").trim();
  const at = written.indexOf("@");
  const ref = at < 0 ? "HEAD" : written.slice(at + 1);
  const found = /^([\w.-]+)\/([\w.-]+)$/.exec(at < 0 ? written : written.slice(0, at));
  if (!found || !/^\S+$/.test(ref)) return null;
  return { owner: found[1], name: found[2].replace(/\.git$/, ""), ref };
}

/** @param {string} path */
function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

/**
 * @param {string} path
 * @param {string | null} token
 */
async function api(path, token) {
  /** @type {Record<string, string>} */
  const headers = { Accept: "application/vnd.github+json" };
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch("https://api.github.com/" + path, { headers });
  if (!response.ok) {
    const limited = response.status === 403 || response.status === 429;
    throw new Error(
      limited
        ? "GitHub's API limit is reached (60 requests an hour without a token): add a token, or try later"
        : `GitHub answered ${response.status} for ${path}`,
    );
  }
  return response.json();
}

/** @param {string[]} urls */
async function fetchBytes(urls) {
  for (const url of urls) {
    for (let attempt = 0; attempt < TRIES; attempt += 1) {
      const response = await fetch(url).catch(() => null);
      if (response && response.ok) return response.arrayBuffer();
      await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
    }
  }
  throw new Error("could not fetch " + urls[0]);
}

/**
 * @param {Repository} repository
 * @param {string | null} token
 * @param {(text: string) => void} progress
 */
async function readRepository(repository, token, progress) {
  const { owner, name, ref } = repository;
  const commit = (await api(`repos/${owner}/${name}/commits/${encodeURIComponent(ref)}`, token)).sha;
  const tree = await api(`repos/${owner}/${name}/git/trees/${commit}?recursive=1`, token);
  /** @type {TreeEntry[]} */
  const entries = tree.tree;
  const blobs = entries.filter((entry) => entry.type === "blob" && entry.mode !== "120000"); // symlinks skipped
  /** @type {Map<number, ProjectFile>} */
  const read = new Map();
  const queue = blobs.entries();
  async function worker() {
    for (const [at, blob] of queue) {
      const path = `${name}/${blob.path}`;
      if (blob.size > MOST_FETCHED) {
        read.set(at, { path, size: blob.size, bytes: null });
      } else {
        const urls = [
          `https://raw.githubusercontent.com/${owner}/${name}/${commit}/${encodePath(blob.path)}`,
          `https://cdn.jsdelivr.net/gh/${owner}/${name}@${commit}/${encodePath(blob.path)}`,
        ];
        read.set(at, { path, size: blob.size, bytes: await fetchBytes(urls) });
      }
      if (read.size % 50 === 0 || read.size === blobs.length) progress(`Fetched ${read.size} of ${blobs.length} files`);
    }
  }
  await Promise.all(Array.from({ length: Math.min(IN_FLIGHT, blobs.length) }, worker));
  const files = blobs.map((_, at) => /** @type {ProjectFile} */ (read.get(at)));
  return { root: name, commit, files, truncated: Boolean(tree.truncated) };
}
