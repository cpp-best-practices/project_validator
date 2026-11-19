"""TypeScript: JavaScript's platform (package.json or deno.json, the Node.js, Deno and Bun runtimes, and their tools,
in the JavaScript profile), with type checking (tsc, deno check) as its defining gate, which JavaScript is not asked
for. A package.json's `main` names the JavaScript a TypeScript package publishes, which makes it no JavaScript
project."""

from __future__ import annotations

from project_validator.ecosystems.javascript import TS_SUFFIXES, TYPESCRIPT, ecmascript_ecosystem

TYPESCRIPT_ECOSYSTEM = ecmascript_ecosystem(TYPESCRIPT, TS_SUFFIXES)
