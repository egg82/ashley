// Bundles the person card harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/person/build.mjs <outdir>; then serve <outdir> and open /?facts=ok.
import { buildHarness } from '../page.mjs';

await buildHarness('harness/person/main.tsx', 'Person harness');
