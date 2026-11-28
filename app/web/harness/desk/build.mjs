// Bundles the Desk harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/desk/build.mjs <outdir>; then serve <outdir> and open /?att=needs.
import { buildHarness } from '../page.mjs';

await buildHarness('harness/desk/main.tsx', 'Desk harness');
