// The repository's files over HTTP, for the browser tests: the page needs a server (a worker does not start from
// file://). Only GET of files below the repository; the port is the first argument.
import { createReadStream, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { ROOT } from "./checkout.mjs";

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css" };

createServer((request, response) => {
  const file = path.join(ROOT, decodeURIComponent(new URL(request.url, "http://localhost").pathname));
  const found = file.startsWith(ROOT + path.sep) && statSync(file, { throwIfNoEntry: false })?.isFile();
  if (!found) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
  createReadStream(file).pipe(response);
}).listen(Number(process.argv[2]));
