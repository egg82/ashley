// Bundles the Desk harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/desk/build.mjs <outdir>; then serve <outdir> and open /?att=needs.
import { build } from 'esbuild';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const outdir = process.argv[2];
if (!outdir) throw new Error('usage: node harness/desk/build.mjs <outdir>');
rmSync(outdir, { recursive: true, force: true });
mkdirSync(outdir, { recursive: true });
await build({
  entryPoints: ['harness/desk/main.tsx'],
  outdir,
  bundle: true,
  format: 'esm',
  target: 'es2022',
  jsx: 'automatic',
  jsxImportSource: 'preact',
  loader: { '.woff2': 'file', '.woff': 'file' },
  assetNames: 'fonts/[name]-[hash]',
});
writeFileSync(join(outdir, 'index.html'), `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Desk harness</title><link rel="stylesheet" href="/main.css"></head>
<body><div id="app"></div><script type="module" src="/main.js"></script></body></html>
`);
console.log(`built into ${outdir}/`);
