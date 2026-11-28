// Bundles the kiosk harness (main.tsx) and its page into <outdir>, apart from the app's own build.
// Usage: node harness/kiosk/build.mjs <outdir>; then serve <outdir> and open / (the fixed page) or /?laid=1.
import { buildHarness } from '../page.mjs';

await buildHarness('harness/kiosk/main.tsx', 'Kiosk harness');
