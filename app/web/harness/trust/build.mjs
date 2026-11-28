// Bundles the trust harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/trust/build.mjs <outdir>; then serve <outdir> and open /?state=ready.
import { buildHarness } from '../page.mjs';

await buildHarness('harness/trust/main.tsx', 'Trust harness');
