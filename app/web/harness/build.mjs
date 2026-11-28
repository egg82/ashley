// Bundles the canvas harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/build.mjs <outdir>; then serve <outdir> and open /?n=11.
import { build } from 'esbuild';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const outdir = process.argv[2];
if (!outdir) throw new Error('usage: node harness/build.mjs <outdir>');
rmSync(outdir, { recursive: true, force: true });
mkdirSync(outdir, { recursive: true });
await build({
  entryPoints: ['harness/main.tsx'],
  outdir,
  bundle: true,
  format: 'esm',
  splitting: true,
  chunkNames: 'chunks/[name]-[hash]',
  target: 'es2022',
  jsx: 'automatic',
  jsxImportSource: 'preact',
  loader: { '.woff2': 'file', '.woff': 'file' },
  assetNames: 'fonts/[name]-[hash]',
});
writeFileSync(join(outdir, 'index.html'), `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bench canvas harness</title><link rel="stylesheet" href="/main.css">
<style>html, body, #app { height: 100%; margin: 0; } #app { position: relative; overflow: hidden; }</style></head>
<body><div id="app"></div><script type="module" src="/main.js"></script></body></html>
`);
console.log(`built into ${outdir}/`);
