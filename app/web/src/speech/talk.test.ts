import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Talk from './talk.ts';

// talk.ts imports extensionless siblings, so it is bundled as the client's own build does and loaded from that bundle.
// Its neighbours are stand-ins that write what they were asked to `globalThis.calls`, in order: the point is what the
// record tap does before the microphone is awaited.
const stubs: Record<string, string> = {
  '../api/client': `export class ApiError extends Error {}`,
  '../api/speech': `export const getSpokenLimits = async () => ({ max_ms: 30000 });`,
  './voice': `export const primeVoice = () => globalThis.calls.push('prime'); export const stopVoice = () => globalThis.calls.push('stop');`,
  './record': `export class MicRefused extends Error {}
    export const record = async () => { globalThis.calls.push('mic'); return { stop: async () => new Blob([]), cancel() {} }; };`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./talk.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js' }));
  } }],
});
const { talk } = (await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0]!.text).toString('base64')}`)) as typeof Talk;
const calls = ((globalThis as { calls?: string[] }).calls = []);
const settle = () => new Promise((resolve) => setImmediate(resolve));

test('the record tap stops her voice and unlocks audio before anything is awaited, and only then opens the microphone', async () => {
  calls.length = 0;
  const talking = talk(async () => ({ text: 'x' }), () => {}, () => {});
  talking.start();
  assert.deepEqual(calls, ['stop', 'prime'], 'both ran in the tap itself');
  await settle();
  assert.deepEqual(calls, ['stop', 'prime', 'mic']);
  talking.cancel();
});

test('words heard are handed on tagged as said aloud', async () => {
  const got: [string, boolean][] = [];
  const talking = talk(async () => ({ text: ' lights on ' }), (text, aloud) => got.push([text, aloud]), () => {});
  talking.start();
  await settle();
  talking.stop();
  await settle();
  assert.deepEqual(got, [['lights on', true]]);
});

test('a press while it is already listening or opening does not stop her voice again', async () => {
  calls.length = 0;
  const talking = talk(async () => ({ text: 'x' }), () => {}, () => {});
  talking.start();
  talking.start();
  assert.deepEqual(calls, ['stop', 'prime']);
  talking.cancel();
});
