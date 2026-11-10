import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as State from './state.ts';

// state.ts reaches the session and the sign-in reveal, which do not run here; both are stand-ins that say nothing is
// wrong. The point is when her mark says she speaks: a reply that landed in text, or her voice sounding on this page.
const stubs: Record<string, string> = {
  '../../session/session': `import { signal } from '@preact/signals'; export const status = signal('ready');`,
  '../../signin/reveal': `import { signal } from '@preact/signals'; export const revealing = signal(false);`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./state.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js',
      resolveDir: fileURLToPath(new URL('../../..', import.meta.url)) }));
  } }],
});
const her = (await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0]!.text).toString('base64')}`)) as typeof State;

test('a reply that lands in text is a moment of speaking, and one this page plays aloud is not', () => {
  her.herRoomLeft();
  her.herAsked();
  her.herReplied(false);
  assert.equal(her.herState.value, 'speaking');
  her.herRoomLeft();
  her.herAsked();
  her.herReplied(true);
  assert.equal(her.herState.value, 'idle');
  her.herSaidLater(true);
  assert.equal(her.herState.value, 'idle');
  her.herSaidLater(false);
  assert.equal(her.herState.value, 'speaking');
  her.herRoomLeft();
});

test('her voice sounding on the page is speaking, for exactly as long as it sounds, and leaving the room ends it', () => {
  her.herRoomLeft();
  her.herVoicePlaying(true);
  assert.equal(her.herState.value, 'speaking');
  her.herVoicePlaying(false);
  assert.equal(her.herState.value, 'idle');
  her.herVoicePlaying(true);
  her.herRoomLeft();
  assert.equal(her.herState.value, 'idle');
});
