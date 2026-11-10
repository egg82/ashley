import assert from 'node:assert/strict';
import { mock, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Voice from './voice.ts';

// voice.ts imports an extensionless sibling, so it is bundled as the client's own build does and loaded from that
// bundle, with the api client replaced by a stand-in and the browser's audio by the fakes below.
const stubs: Record<string, string> = {
  '../api/client': `export const chatVoiceUrl = (id) => '/chat/' + id;
    export const getSpokenLimits = async () => ({ max_ms: 30000, voice_s: 120 });`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./voice.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js' }));
  } }],
});
const code = built.outputFiles[0]!.text;
const voice = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)) as typeof Voice;

class FakeAudio {
  static made: FakeAudio[] = [];
  static refuse: 'none' | 'blocked' | 'other' = 'none';
  src = '';
  played: string[] = [];
  paused = 0;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onplaying: (() => void) | null = null;
  constructor() {
    FakeAudio.made.push(this);
  }
  play(): Promise<void> {
    this.played.push(this.src);
    if (this.src.startsWith('data:')) return Promise.resolve();
    if (FakeAudio.refuse === 'blocked') return Promise.reject(new DOMException('no', 'NotAllowedError'));
    return FakeAudio.refuse === 'other' ? Promise.reject(new DOMException('no', 'AbortError')) : Promise.resolve();
  }
  pause(): void {
    this.paused++;
  }
}
class FakeContext {
  static made: FakeContext[] = [];
  resumed = 0;
  started = 0;
  sampleRate = 48000;
  destination = {};
  constructor() {
    FakeContext.made.push(this);
  }
  resume(): Promise<void> {
    this.resumed++;
    return Promise.resolve();
  }
  createBuffer(channels: number, length: number): { channels: number; length: number } {
    return { channels, length };
  }
  createBufferSource(): { buffer: unknown; connect: () => void; start: () => void } {
    const owner = this;
    return { buffer: null, connect() {}, start() { owner.started++; } };
  }
}
Object.assign(globalThis, { Audio: FakeAudio, AudioContext: FakeContext });

const settle = () => new Promise((resolve) => setImmediate(resolve));
const turn = (id: number, over: Partial<Voice.VoiceTurn> = {}): Voice.VoiceTurn =>
  ({ id, author: 'ashley', follows: false, voiced: true, ...over });
const elementPlayed = () => FakeAudio.made[0]!.played.filter((src) => !src.startsWith('data:'));
const reset = () => { voice.stopVoice(); FakeAudio.refuse = 'none'; FakeAudio.made[0] && (FakeAudio.made[0].played = []); };

test('priming makes one audio element and one context, resumes the context and plays a silent buffer, each time', () => {
  reset();
  voice.primeVoice();
  voice.primeVoice();
  assert.equal(FakeAudio.made.length, 1);
  assert.equal(FakeContext.made.length, 1);
  assert.equal(FakeContext.made[0]!.resumed, 2);
  assert.equal(FakeContext.made[0]!.started, 2);
});

test('a window plays a voiced turn that is new since the send, once, and not an older one', async () => {
  reset();
  voice.awaitVoice(new Set([1]));
  voice.offer([turn(1), turn(2)]);
  voice.offer([turn(1), turn(2)]);
  assert.deepEqual(elementPlayed(), ['/chat/2']);
  assert.deepEqual(voice.state.value, { turn: 2, phase: 'playing' });
});

test('with no window nothing plays: a typed send, or another tab, opens none', () => {
  reset();
  voice.offer([turn(5)]);
  assert.deepEqual(elementPlayed(), []);
  voice.awaitVoice(new Set());
  voice.stopVoice();
  voice.offer([turn(6)]);
  assert.deepEqual(elementPlayed(), []);
});

test('a turn that is not hers or not voiced does not play', () => {
  reset();
  voice.awaitVoice(new Set());
  voice.offer([turn(1, { author: 'person' }), turn(2, { voiced: false }), turn(3, { author: 'household' })]);
  assert.deepEqual(elementPlayed(), []);
});

test('the window closes on her first turn that does not follow, and a held line and its answer play in order', async () => {
  reset();
  voice.awaitVoice(new Set());
  voice.offer([turn(1, { follows: true })]);
  voice.offer([turn(1, { follows: true }), turn(2)]);
  assert.deepEqual(elementPlayed(), ['/chat/1'], 'the answer waits for the held line to end');
  FakeAudio.made[0]!.onended?.();
  assert.deepEqual(elementPlayed(), ['/chat/1', '/chat/2']);
  FakeAudio.made[0]!.onended?.();
  assert.equal(voice.state.value, null);
  voice.offer([turn(1, { follows: true }), turn(2), turn(3)]);
  assert.deepEqual(elementPlayed(), ['/chat/1', '/chat/2'], 'closed by her answer, so a later turn is not played');
});

test('the window closes after voice_s and on the next send', async () => {
  reset();
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    voice.awaitVoice(new Set());
    await settle();
    mock.timers.tick(119_000);
    voice.offer([turn(1, { follows: true })]);
    assert.deepEqual(elementPlayed(), ['/chat/1']);
    FakeAudio.made[0]!.onended?.();
    voice.awaitVoice(new Set([1]));
    await settle();
    mock.timers.tick(121_000);
    voice.offer([turn(9)]);
    assert.deepEqual(elementPlayed(), ['/chat/1']);
  } finally {
    mock.timers.reset();
  }
  reset();
  voice.awaitVoice(new Set());
  voice.awaitVoice(new Set());
  voice.offer([turn(1)]);
  assert.deepEqual(elementPlayed(), ['/chat/1'], 'a second send replaces the window, it does not double it');
});

test('stopping pauses the audio, forgets what was queued and shows nothing', () => {
  reset();
  voice.awaitVoice(new Set());
  voice.offer([turn(1, { follows: true }), turn(2)]);
  const before = FakeAudio.made[0]!.paused;
  const ended = FakeAudio.made[0]!.onended;
  voice.stopVoice();
  assert.equal(FakeAudio.made[0]!.paused, before + 1);
  assert.equal(voice.state.value, null);
  ended?.();
  assert.deepEqual(elementPlayed(), ['/chat/1'], 'the queued turn does not start after a stop');
});

test('a browser that refuses to play shows a play control on that turn, and a tap plays it', async () => {
  reset();
  FakeAudio.refuse = 'blocked';
  voice.awaitVoice(new Set());
  voice.offer([turn(4)]);
  await settle();
  assert.deepEqual(voice.state.value, { turn: 4, phase: 'blocked' });
  FakeAudio.refuse = 'none';
  voice.playTurn(4);
  await settle();
  assert.deepEqual(voice.state.value, { turn: 4, phase: 'playing' });
  assert.deepEqual(elementPlayed(), ['/chat/4', '/chat/4']);
});

test('a voice that cannot be fetched shows nothing and the next turn goes on', async () => {
  reset();
  voice.awaitVoice(new Set());
  voice.offer([turn(1, { follows: true }), turn(2)]);
  FakeAudio.made[0]!.onerror?.();
  assert.deepEqual(elementPlayed(), ['/chat/1', '/chat/2']);
  FakeAudio.made[0]!.onerror?.();
  assert.equal(voice.state.value, null);
});

test('a play that fails for another reason than a refusal is dropped without a control', async () => {
  reset();
  FakeAudio.refuse = 'other';
  voice.awaitVoice(new Set());
  voice.offer([turn(1)]);
  await settle();
  assert.equal(voice.state.value, null);
});

test('the route can be switched to the kiosk', () => {
  reset();
  voice.voiceRoute((id) => `/kiosk/${id}`);
  voice.awaitVoice(new Set());
  voice.offer([turn(7)]);
  assert.deepEqual(elementPlayed(), ['/kiosk/7']);
  voice.voiceRoute((id) => `/chat/${id}`);
});

test('she is sounding only once the element says it plays: not while fetching, not blocked, not after a stop or the end', async () => {
  reset();
  voice.awaitVoice(new Set());
  voice.offer([turn(7)]);
  await settle();
  assert.equal(voice.sounding.value, false, 'asked to play, not yet audible');
  FakeAudio.made[0]!.onplaying?.();
  assert.equal(voice.sounding.value, true);
  FakeAudio.made[0]!.onended?.();
  assert.equal(voice.sounding.value, false);
  voice.playTurn(7);
  FakeAudio.made[0]!.onplaying?.();
  voice.stopVoice();
  assert.equal(voice.sounding.value, false);
  assert.equal(FakeAudio.made[0]!.onplaying, null);
  FakeAudio.refuse = 'blocked';
  voice.awaitVoice(new Set());
  voice.offer([turn(8)]);
  await settle();
  assert.equal(voice.sounding.value, false, 'blocked is not sounding');
});

test('the page owns the answer from the send until the turn is over: window open, playing or blocked', async () => {
  reset();
  assert.equal(voice.owns(), false);
  voice.awaitVoice(new Set());
  assert.equal(voice.owns(), true);
  voice.offer([turn(9, { voiced: false })]);
  assert.equal(voice.owns(), false, 'her unvoiced answer closed the window');
  voice.awaitVoice(new Set());
  voice.offer([turn(10)]);
  assert.equal(voice.owns(), true, 'playing');
  voice.stopVoice();
  assert.equal(voice.owns(), false);
});

test('an element error ends the turn quietly: nothing is logged and the next one goes on', async () => {
  reset();
  const logged: unknown[] = [];
  const error = console.error;
  console.error = (...args: unknown[]) => void logged.push(args);
  try {
    voice.awaitVoice(new Set());
    voice.offer([turn(11, { follows: true }), turn(12)]);
    FakeAudio.made[0]!.onerror?.();
    assert.deepEqual(voice.state.value, { turn: 12, phase: 'playing' });
    assert.deepEqual(logged, []);
  } finally {
    console.error = error;
  }
});
