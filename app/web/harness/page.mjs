// Bundles one harness entry and its page into an outdir, apart from the app's own build. Each harness's build.mjs calls it.
import { build } from 'esbuild';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export async function buildHarness(entry, title) {
  const outdir = process.argv[2];
  if (!outdir) throw new Error(`usage: node ${entry.replace(/main\.tsx$/, 'build.mjs')} <outdir>`);
  rmSync(outdir, { recursive: true, force: true });
  mkdirSync(outdir, { recursive: true });
  await build({
    entryPoints: [entry],
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
<title>${title}</title><link rel="stylesheet" href="/main.css"></head>
<body><div id="app"></div><script type="module" src="/main.js"></script></body></html>
`);
  console.log(`built into ${outdir}/`);
}
