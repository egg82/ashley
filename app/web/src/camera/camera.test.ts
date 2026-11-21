import assert from 'node:assert/strict';
import { afterEach, beforeEach, mock, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Card from './card.ts';
import type * as Connect from './connect.ts';
import type * as Swipe from './swipe.ts';
import type { FeedRoutes } from '../api/screenFeed.ts';
import type { ScreenFeed } from '../api/types.ts';

// The camera modules import extensionless siblings, so they are bundled as the client's own build does and loaded from
// that bundle; the api client (which these never call) is replaced by the one class they take from it.
const built = await build({
  stdin: { contents: "export * from './card'; export * from './connect'; export * from './swipe';",
           resolveDir: fileURLToPath(new URL('.', import.meta.url)), loader: 'ts' },
  bundle: true, write: false, format: 'esm', platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /^\.\/client$/ }, (args) => ({ path: args.path, namespace: 'stub' }));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({ contents: 'export class ApiError extends Error { constructor(s) { super(String(s)); this.status = s; } }', loader: 'js' }));
  } }],
});
const lib = (await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0]!.text).toString('base64')}`)) as
  typeof Card & typeof Connect & typeof Swipe;

const FEED: ScreenFeed = { camera_title: 'Porch', remaining_s: 90, data_channel: null, ice_servers: [
  { urls: ['stun:stun.example.test:3478'], username: null, credential: null },
  { urls: ['turn:turn.example.test:3478'], username: 'zq-user', credential: 'zq-pass' }] };

interface Calls { read: number; dismissed: string[]; offers: string[]; candidates: string[][]; }
let calls: Calls;
let reads: Array<ScreenFeed | null | Error>;
let streamed: string[];
let ends: boolean;

function bytes(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  // an open feed's stream stays open; the server ends it only when the feed's time is up
  return new ReadableStream({ start(c) { lines.forEach((l) => c.enqueue(encoder.encode(l))); if (ends) c.close(); } });
}

const data = (signal: object) => `data: ${JSON.stringify(signal)}\n\n`;

const routes: FeedRoutes = {
  async read() {
    calls.read++;
    const next = reads.shift();
    if (next instanceof Error) throw next;
    return next ?? null;
  },
  async dismiss(screen) { calls.dismissed.push(screen); },
  async offer(_screen, sdp) { calls.offers.push(sdp); return bytes(streamed); },
  async candidate(_screen, session, init) { calls.candidates.push([session, init.candidate ?? '', String(init.sdpMid)]); },
};

class FakePeer {
  static made: FakePeer[] = [];
  config: RTCConfiguration;
  channels: string[] = [];
  transceivers: string[] = [];
  remote: RTCSessionDescriptionInit | undefined;
  added: RTCIceCandidateInit[] = [];
  closed = 0;
  connectionState = 'new';
  onicecandidate: ((e: { candidate: { candidate: string; toJSON(): RTCIceCandidateInit } | null }) => void) | null = null;
  ontrack: ((e: { streams: unknown[]; track: unknown }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  constructor(config: RTCConfiguration) { this.config = config; FakePeer.made.push(this); }
  createDataChannel(name: string) { this.channels.push(name); }
  addTransceiver(kind: string) { this.transceivers.push(kind); }
  async createOffer() { return { type: 'offer', sdp: 'v=0 zqoffer\r\n' }; }
  async setLocalDescription() {
    this.onicecandidate?.({ candidate: { candidate: 'candidate:gathered', toJSON: () => ({ candidate: 'candidate:gathered', sdpMid: '0' }) } });
  }
  async setRemoteDescription(d: RTCSessionDescriptionInit) { this.remote = d; }
  async addIceCandidate(c: RTCIceCandidateInit) { this.added.push(c); }
  close() { this.closed++; }
  candidate(line: string) {
    this.onicecandidate?.({ candidate: { candidate: line, toJSON: () => ({ candidate: line, sdpMid: '0' }) } });
  }
}
const browser = { peer: (config: RTCConfiguration) => new FakePeer(config) as unknown as RTCPeerConnection };
const video = { muted: false, srcObject: null as unknown, played: 0, play() { this.played++; return Promise.resolve(); } };
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };
const open = (failed: () => void, on = browser) =>
  lib.connect(routes, 'tok', FEED, video as unknown as HTMLVideoElement, failed, on);

const cards: Card.Card[] = [];
const fresh = (): Card.Card => {
  const card = lib.createCard(routes, 'tok');
  cards.push(card);
  return card;
};

afterEach(() => {
  cards.splice(0).forEach((c) => c.dismiss());   // a card's own leave timer would hold the process open
});

beforeEach(() => {
  calls = { read: 0, dismissed: [], offers: [], candidates: [] };
  reads = [];
  streamed = [];
  ends = false;
  FakePeer.made = [];
  Object.assign(video, { muted: false, srcObject: null, played: 0 });
});

test('a drag of 96 pixels or more either way is a swipe away, a lesser one is not', () => {
  assert.deepEqual([0, 95, -95].map(lib.swiped), [false, false, false]);
  assert.deepEqual([96, -96, 400].map(lib.swiped), [true, true, true]);
});

test('a screen shows the feed it reads as connecting, then live once the picture plays, and no card for none', async () => {
  const card = fresh();
  reads = [FEED, FEED, null];
  await card.read();
  assert.deepEqual(card.showing.value, { feed: FEED, phase: 'connecting' });
  card.playing();
  assert.equal(card.showing.value?.phase, 'live');
  await card.read();
  assert.equal(card.showing.value?.phase, 'live', 'the same camera read again is not a new connection');
  await card.read();
  assert.equal(card.showing.value, null);
  card.playing();
  assert.equal(card.showing.value, null);
});

test('another camera replaces the card and starts connecting again', async () => {
  const card = fresh();
  reads = [FEED, { ...FEED, camera_title: 'Hall' }];
  await card.read();
  card.playing();
  await card.read();
  assert.deepEqual([card.showing.value?.feed.camera_title, card.showing.value?.phase], ['Hall', 'connecting']);
});

test('the card leaves on its own once the seconds the server gave are up', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const card = fresh();
    reads = [FEED];
    await card.read();
    mock.timers.tick(FEED.remaining_s * 1000 - 1);
    assert.notEqual(card.showing.value, null);
    mock.timers.tick(1);
    assert.equal(card.showing.value, null);
  } finally {
    mock.timers.reset();
  }
});

test('a swipe takes the card off at once and tells the server for this screen', async () => {
  const card = fresh();
  reads = [FEED];
  await card.read();
  card.dismiss();
  assert.equal(card.showing.value, null);
  assert.deepEqual(calls.dismissed, ['tok']);
});

test('a read that fails leaves what is shown, and a failed feed says so rather than going blank', async () => {
  const card = fresh();
  reads = [FEED, new Error('503')];
  await card.read();
  await card.read();
  assert.equal(card.showing.value?.phase, 'connecting');
  card.failed();
  assert.deepEqual(card.showing.value, { feed: FEED, phase: 'failed' });
});

test('the offer carries the candidates gathered while it was made, and the camera is given ice servers and a data channel', async () => {
  streamed = [data({ type: 'session', session_id: 'S1' })];
  const link = lib.connect(routes, 'tok', { ...FEED, data_channel: 'dataSendChannel' }, video as unknown as HTMLVideoElement,
    () => assert.fail('failed'), browser);
  await settle();
  const peer = FakePeer.made[0]!;
  assert.deepEqual(calls.offers, ['v=0 zqoffer\r\na=candidate:gathered\r\n']);
  assert.deepEqual(peer.config.iceServers, [{ urls: ['stun:stun.example.test:3478'] },
    { urls: ['turn:turn.example.test:3478'], username: 'zq-user', credential: 'zq-pass' }]);
  assert.deepEqual([peer.channels, peer.transceivers], [['dataSendChannel'], ['video', 'audio']]);
  assert.deepEqual(calls.candidates, [], 'the gathered one went in the offer, not again');
  link.close();
});

test('later candidates go once the session is named, and the answer and the camera candidates are applied', async () => {
  streamed = [data({ type: 'session', session_id: 'S1' }), data({ type: 'answer', answer: 'v=0 zqanswer' }),
    data({ type: 'candidate', candidate: 'candidate:cam1', sdp_mid: null, sdp_m_line_index: null, username_fragment: null }),
    data({ type: 'candidate', candidate: 'candidate:cam2', sdp_mid: '1', sdp_m_line_index: 1, username_fragment: 'f' })];
  const link = open(() => assert.fail('failed'));
  await settle();
  const peer = FakePeer.made[0]!;
  peer.candidate('candidate:late');
  assert.deepEqual(calls.candidates, [['S1', 'candidate:late', '0']]);
  assert.deepEqual(peer.remote, { type: 'answer', sdp: 'v=0 zqanswer' });
  assert.deepEqual(peer.added, [{ candidate: 'candidate:cam1', sdpMid: '0', sdpMLineIndex: null, usernameFragment: null },
    { candidate: 'candidate:cam2', sdpMid: '1', sdpMLineIndex: 1, usernameFragment: 'f' }]);
  link.close();
});

test('the picture plays muted when it arrives, and the connect timer stops', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    let failed = 0;
    const link = open(() => failed++);
    await settle();
    FakePeer.made[0]!.ontrack!({ streams: ['the-stream'], track: {} });
    assert.deepEqual([video.muted, video.srcObject, video.played], [true, 'the-stream', 1]);
    mock.timers.tick(lib.CONNECT_MS);
    assert.equal(failed, 0);
    link.close();
  } finally {
    mock.timers.reset();
  }
});

test('an error signal, a refused offer, a stream that ends, a failed connection and silence each fail it once', async () => {
  const scenarios: Array<() => Promise<number>> = [
    async () => { streamed = [data({ type: 'error', code: 'x' })]; return 0; },
    async () => { streamed = []; ends = true; return 0; },
    async () => { streamed = [data({ type: 'session', session_id: 'S1' })]; ends = true; return 0; },
  ];
  for (const arrange of scenarios) {
    await arrange();
    let failed = 0;
    open(() => failed++);
    await settle();
    assert.equal(failed, 1);
    assert.equal(FakePeer.made.at(-1)!.closed, 1);
  }
  const refusing = { ...routes, offer: () => Promise.reject(new Error('404')) };
  let refused = 0;
  lib.connect(refusing, 'tok', FEED, video as unknown as HTMLVideoElement, () => refused++, browser);
  await settle();
  assert.equal(refused, 1);
  let dropped = 0;
  streamed = [data({ type: 'session', session_id: 'S1' })];
  ends = true;
  open(() => dropped++);
  await settle();
  const peer = FakePeer.made.at(-1)!;
  assert.equal(dropped, 1, 'the stream ending already failed it');
  peer.connectionState = 'failed';
  peer.onconnectionstatechange!();
  assert.equal(dropped, 1, 'and a later failure does not fail it twice');
});

test('no media within the connect time fails it, and closing it ends it without a failure', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    let failed = 0;
    open(() => failed++);
    await settle();
    mock.timers.tick(lib.CONNECT_MS);
    assert.equal(failed, 1);
    let quiet = 0;
    const link = open(() => quiet++);
    link.close();
    link.close();
    mock.timers.tick(lib.CONNECT_MS);
    await settle();
    assert.deepEqual([quiet, FakePeer.made.at(-1)!.closed], [0, 1]);
  } finally {
    mock.timers.reset();
  }
});
