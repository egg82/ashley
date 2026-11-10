// Fails when src/api/schema.d.ts is not what openapi-typescript generates from ../openapi.json now.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const dir = mkdtempSync(join(tmpdir(), 'ashley-types-'));
try {
  const fresh = join(dir, 'schema.d.ts');
  execFileSync('npx', ['openapi-typescript', '../openapi.json', '-o', fresh], { stdio: 'ignore' });
  if (readFileSync(fresh, 'utf8') !== readFileSync('src/api/schema.d.ts', 'utf8')) {
    console.error('src/api/schema.d.ts is stale: run `npm run types` in app/web and commit it');
    process.exit(1);
  }
  console.log('src/api/schema.d.ts matches ../openapi.json');
} finally {
  rmSync(dir, { recursive: true, force: true });
}
