import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Chat from './chat.ts';

// chat.ts reaches the api, the live feed, the session, her state and the voice owner, none of which runs here: each is a
// stand-in, and the voice owner and the api write what they were asked to `globalThis.calls`, in order. The point is
// what the room tells the voice owner when a message is sent, typed or said aloud, and what it offers it on a read.
const stubs: Record<string, string> = {
  '../../api/client': `export class ApiError extends Error {}
    export const chatVoiceUrl = (id) => '/chat/' + id;
    export const sendChat = async (body) => { globalThis.calls.push(['send', body.said_aloud]); return { conversation_id: 1, body: 'ok', follows: false }; };
    export const getChat = async () => globalThis.conversation;
    export const transcribeChat = async () => ({ text: '' });
    export const rememberTurn = async () => ({});`,
  '../../session/live': `export const liveUp = { value: true }; export const onResync = () => () => {};
    export const onThreadTurn = () => () => {}; export const onTurnFailed = () => () => {};`,
  '../../session/session': `export const load = async () => {};`,
  '../../shell/carry': `export const acknowledge = () => {};`,
  '../../shell/her/state': `const none = () => {};
    export const herAsked = none, herHears = none, herNoReply = none, herRoomLeft = none, herWorking = none,
      roomReached = none, herRemembered = none, herRemembering = none;
    export const herVoicePlaying = (on) => globalThis.landed.push(['playing', on]);
    export const herReplied = (voiced) => globalThis.landed.push(['replied', voiced]);
    export const herSaidLater = (voiced) => globalThis.landed.push(['later', voiced]);
    export const herState = { value: 'idle' };`,
  '../../speech/talk': `export const talk = () => ({ cancel() {} });`,
  '../../speech/voice': `export const awaitVoice = (seen) => globalThis.calls.push(['await', [...seen]]);
    export const stopVoice = () => globalThis.calls.push(['stop']);
    export const offer = (turns) => globalThis.calls.push(['offer', turns]);
    export const voiceRoute = (urlOf) => globalThis.calls.push(['route', urlOf(3)]);
    export const owns = () => globalThis.owned;
    import { signal } from '@preact/signals';
    export const sounding = signal(false); globalThis.sounding = sounding;`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./chat.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js',
      resolveDir: fileURLToPath(new URL('../../..', import.meta.url)) }));
  } }],
});
const chat = (await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0]!.text).toString('base64')}`)) as typeof Chat;
const g = globalThis as { calls?: unknown[]; landed?: unknown[]; owned?: boolean; conversation?: unknown; sounding?: { value: boolean } };
const calls = (g.calls = []);
const landed = (g.landed = []);
const turn = (id: number, author: string, voiced = false) => ({
  id, author, text: 't', at: '2026-11-08T10:00:00Z', follows: false, continued_on: null, attachment: null, runs: [],
  looks: [], working: false, agree: null, voiced,
});
g.conversation = {
  thread: 'person:1:web', conversation_id: 1, started_at: '2026-11-08T10:00:00Z',
  turns: [turn(1, 'person'), turn(2, 'ashley', true)],
};

test('entering the room points the voice owner at the person\'s own route', () => {
  calls.length = 0;
  chat.enterRoom();
  assert.deepEqual(calls[0], ['route', '/chat/3']);
  chat.leaveRoom();
});

test('a message said aloud opens the window with the turns already shown, a typed one stops the voice', async () => {
  await chat.loadChat();
  calls.length = 0;
  await chat.send('lights on', null, true);
  assert.deepEqual(calls.filter((c) => (c as unknown[])[0] === 'await'), [['await', [1, 2]]]);
  assert.deepEqual(calls.filter((c) => (c as unknown[])[0] === 'send'), [['send', true]]);
  calls.length = 0;
  await chat.send('lights off');
  assert.deepEqual(calls.filter((c) => (c as unknown[])[0] === 'await'), []);
  assert.deepEqual(calls[0], ['stop']);
  assert.deepEqual(calls.filter((c) => (c as unknown[])[0] === 'send'), [['send', false]]);
});

test('every read offers the turns with their voiced flag', async () => {
  calls.length = 0;
  await chat.refresh();
  assert.deepEqual(calls.find((c) => (c as unknown[])[0] === 'offer'), ['offer', [
    { id: 1, author: 'person', follows: false, voiced: false }, { id: 2, author: 'ashley', follows: false, voiced: true }]]);
});

test('leaving the room stops the voice', () => {
  chat.enterRoom();
  calls.length = 0;
  chat.leaveRoom();
  assert.ok(calls.some((c) => (c as unknown[])[0] === 'stop'));
});

test('a reply lands as a moment of speaking only when this page does not hold its voice', async () => {
  for (const owned of [true, false]) {
    g.owned = owned;
    landed.length = 0;
    await chat.send('lights on', null, true);
    assert.deepEqual(landed.filter((l) => (l as unknown[])[0] === 'replied'), [['replied', owned]]);
  }
});

test('a reply read back later is a moment of speaking only when this page does not hold its voice', async () => {
  const more = [...(g.conversation as { turns: unknown[] }).turns, turn(3, 'ashley')];
  for (const owned of [true, false]) {
    g.owned = owned;
    g.conversation = { ...(g.conversation as object), turns: more.slice(0, 2) };
    await chat.refresh();
    landed.length = 0;
    g.conversation = { ...(g.conversation as object), turns: [...more.slice(0, 2), turn(owned ? 3 : 4, 'ashley')] };
    await chat.refresh();
    assert.deepEqual(landed.filter((l) => (l as unknown[])[0] === 'later'), [['later', owned]]);
  }
});

test('her state hears when her voice sounds, while the room is shown', () => {
  chat.enterRoom();
  try {
    landed.length = 0;
    g.sounding!.value = true;
    g.sounding!.value = false;
    assert.deepEqual(landed.filter((l) => (l as unknown[])[0] === 'playing'), [['playing', true], ['playing', false]]);
  } finally {
    chat.leaveRoom();
  }
});
