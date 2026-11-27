// A public GitHub repository, read into the page (upstream #127): the ref resolved to a commit, its whole tree listed,
// and every file fetched from raw.githubusercontent.com, with retries and jsDelivr as the fallback (the archives
// GitHub serves refuse a page's requests). Two API calls a run: 60 an hour without a token, 5000 with one.
"use strict";

// Files larger than this are not fetched: their size alone is given, as large-files asks for nothing else.
const MOST_FETCHED = 1024 * 1024;
const IN_FLIGHT = 32;
const TRIES = 3;

function parseRepository(text) {
  // "owner/name@ref" (the ref may hold slashes: a branch, a tag, a commit); the default branch when none is given.
  const found = /^\s*([\w.-]+)\/([\w.-]+?)(?:\.git)?(?:@(\S+))?\s*$/.exec(text || "");
  return found ? { owner: found[1], name: found[2], ref: found[3] || "HEAD" } : null;
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

async function api(path, token) {
  const headers = { Accept: "application/vnd.github+json" };
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch("https://api.github.com/" + path, { headers });
  if (!response.ok) {
    const limited = response.status === 403 || response.status === 429;
    throw new Error(
      limited
        ? "GitHub's API limit is reached (60 requests an hour without a token): add a token, or try later"
        : `GitHub answered ${response.status} for ${path}`
    );
  }
  return response.json();
}

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

async function readRepository(repository, token, progress) {
  const { owner, name, ref } = repository;
  const commit = (await api(`repos/${owner}/${name}/commits/${encodeURIComponent(ref)}`, token)).sha;
  const tree = await api(`repos/${owner}/${name}/git/trees/${commit}?recursive=1`, token);
  const blobs = tree.tree.filter((entry) => entry.type === "blob" && entry.mode !== "120000"); // symlinks skipped
  const files = new Array(blobs.length);
  let next = 0;
  let done = 0;
  async function worker() {
    while (next < blobs.length) {
      const at = next++;
      const blob = blobs[at];
      const path = `${name}/${blob.path}`;
      if (blob.size > MOST_FETCHED) {
        files[at] = { path, size: blob.size, bytes: null };
      } else {
        const urls = [
          `https://raw.githubusercontent.com/${owner}/${name}/${commit}/${encodePath(blob.path)}`,
          `https://cdn.jsdelivr.net/gh/${owner}/${name}@${commit}/${encodePath(blob.path)}`,
        ];
        files[at] = { path, size: blob.size, bytes: await fetchBytes(urls) };
      }
      done += 1;
      if (done % 50 === 0 || done === blobs.length) progress(`Fetched ${done} of ${blobs.length} files`);
    }
  }
  await Promise.all(Array.from({ length: Math.min(IN_FLIGHT, blobs.length) }, worker));
  return { root: name, commit, files, truncated: Boolean(tree.truncated) };
}

if (typeof module !== "undefined") module.exports = { parseRepository, encodePath, readRepository };
