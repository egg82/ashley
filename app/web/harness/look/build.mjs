// Bundles the look harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/look/build.mjs <outdir>; then serve <outdir> and open /?n=11.
import { buildHarness } from '../page.mjs';

await buildHarness('harness/look/main.tsx', 'Look harness');
