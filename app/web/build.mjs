// Bundles src/main.tsx (and the CSS and font files it imports, into main.css and fonts/; what it imports lazily, such as the highlighter's grammars, into chunks/) and copies src/index.html, the manifest, the service worker (sw.js, served at /sw.js) and the icons into ../build/ (gitignored), which the Python app serves at /.
// Usage: node build.mjs [outdir]
import { build } from 'esbuild';
import { copyFileSync, cpSync, mkdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';

const outdir = process.argv[2] ?? '../build';

rmSync(outdir, { recursive: true, force: true });
mkdirSync(outdir, { recursive: true });
await build({
  entryPoints: ['src/main.tsx'],
  outdir,
  bundle: true,
  format: 'esm',
  splitting: true,
  chunkNames: 'chunks/[name]-[hash]',
  target: 'es2022',
  jsx: 'automatic',
  jsxImportSource: 'preact',
  minify: true,
  sourcemap: true,
  loader: { '.woff2': 'file', '.woff': 'file' },
  assetNames: 'fonts/[name]-[hash]',
});
copyFileSync('src/index.html', join(outdir, 'index.html'));
copyFileSync('src/manifest.webmanifest', join(outdir, 'manifest.webmanifest'));
copyFileSync('src/sw.js', join(outdir, 'sw.js'));
copyFileSync('icons/favicon.svg', join(outdir, 'favicon.svg'));
cpSync('icons/generated', outdir, { recursive: true });
console.log(`built into ${outdir}/`);
