import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Kiosk from './state.ts';

// state.ts reaches the api, the live feed, the build watcher and tap to talk, none of which runs here: each is a
// stand-in, and the api and the voice owner write what they were asked to `globalThis.calls`, in order. The point is
// what the kiosk tells the voice owner and what its mark says while her voice is held.
const stubs: Record<string, string> = {
  '../api/client': `export class ApiError extends Error {}
    export const sendKiosk = async (body) => { globalThis.calls.push(['send', body.said_aloud]); return { body: 'ok', follows: false }; };
    export const getKioskConversation = async () => globalThis.conversation;
    export const getKioskControls = async () => [], getKioskDevice = async () => ({}), getKioskGlance = async () => ({}), getKioskLayout = async () => ({ laid_out: false, seq: 0, placed: [] }),
      pairKiosk = async () => ({}), runKioskControl = async () => true;`,
  '../api/speech': `export const kioskVoiceUrl = (id) => '/kiosk/' + id;
    export const transcribeKiosk = async () => ({ text: '' });`,
  '../rooms/her/owed': `export const owedAt = () => -1;`,
  '../session/watch': `export const watchBuild = () => ({ check() {}, stop() {} });`,
  '../speech/talk': `export const talk = () => ({ phase: { value: 'idle' }, cancel() {} });`,
  './live': `import { signal } from '@preact/signals';
    export const liveMark = signal('idle'), liveUp = signal(false);
    export const startLive = () => () => {}, listenScreen = () => {};`,
  './polling': `export const POLL_MS = { conversation: 1e9, glance: 1e9 }; export const polled = () => false;`,
  '../speech/voice': `import { signal } from '@preact/signals';
    export const sounding = signal(false); globalThis.sounding = sounding;
    export const awaitVoice = (seen) => globalThis.calls.push(['await', [...seen]]);
    export const stopVoice = () => globalThis.calls.push(['stop']);
    export const offer = (turns) => globalThis.calls.push(['offer', turns]);
    export const voiceRoute = (urlOf) => globalThis.calls.push(['route', urlOf(3)]);
    export const owns = () => globalThis.owned;`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./state.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js',
      resolveDir: fileURLToPath(new URL('../..', import.meta.url)) }));
  } }],
});
const kiosk = (await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0]!.text).toString('base64')}`)) as typeof Kiosk;
const g = globalThis as { calls?: unknown[]; owned?: boolean; conversation?: unknown; sounding?: { value: boolean } };
const calls = (g.calls = []);
const turn = (id: number, author: string, voiced = false) => ({
  id, author, text: 't', at: '2026-11-08T10:00:00Z', follows: false, continued_on: null, attachment: null, runs: [],
  looks: [], working: false, agree: null, voiced,
});
g.conversation = { thread: 'device:7', conversation_id: 1, started_at: '2026-11-08T10:00:00Z',
                   turns: [turn(1, 'person'), turn(2, 'ashley', true)] };
const of = (name: string) => calls.filter((c) => (c as unknown[])[0] === name);

test('the feed points the voice owner at the kiosk\'s own route, and stopping it stops the voice', () => {
  calls.length = 0;
  const stop = kiosk.startFeed();
  assert.deepEqual(calls[0], ['route', '/kiosk/3']);
  calls.length = 0;
  stop();
  assert.deepEqual(calls, [['stop']]);
});

test('a message said aloud opens the window with the turns shown and is sent tagged; a typed one stops the voice', async () => {
  g.owned = true;
  await kiosk.refresh('conversation');
  calls.length = 0;
  await kiosk.send('lights on', true);
  assert.deepEqual(of('await'), [['await', [1, 2]]]);
  assert.deepEqual(of('send'), [['send', true]]);
  assert.equal(of('offer').length, 1, 'the read after an aloud send offers what came back');
  calls.length = 0;
  await kiosk.send('lights off');
  assert.deepEqual(of('await'), []);
  assert.deepEqual(calls[0], ['stop']);
  assert.deepEqual(of('send'), [['send', false]]);
});

test('every read offers the turns with their voiced flag', async () => {
  calls.length = 0;
  await kiosk.refresh('conversation');
  assert.deepEqual(of('offer'), [['offer', [
    { id: 1, author: 'person', follows: false, voiced: false }, { id: 2, author: 'ashley', follows: false, voiced: true }]]]);
});

test('her mark speaks while the voice sounds, and for a moment as a reply lands unless this page holds its voice', async () => {
  g.owned = true;
  await kiosk.send('b', true);
  assert.equal(kiosk.mark.value, 'idle', 'its voice is the page\'s to play');
  g.sounding!.value = true;
  assert.equal(kiosk.mark.value, 'speaking');
  g.sounding!.value = false;
  assert.equal(kiosk.mark.value, 'idle');
  g.owned = false;
  await kiosk.send('a');
  assert.equal(kiosk.mark.value, 'speaking', 'a reply that is text only');
});
