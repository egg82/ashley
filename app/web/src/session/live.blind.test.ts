import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type { Cue } from '../rooms/workshop/pieces/player';
import type * as Live from './live.ts';

type CueBy = Live.CueBy;

// live.ts imports extensionless siblings and a parameter property, which node's strip-only loader cannot run, so the
// module is bundled as the client's own build does and loaded from that bundle. Its neighbours (the feed, her state, the
// api client) read browser globals on load and none is exercised here, so each is replaced by an empty stand-in.
const stubs: Record<string, string> = {
  '../api/client': 'export const liveFeed = () => null;',
  '../shell/her/moves': 'export const herMoved = () => {}; export const benchChangedBy = (...a) => { (globalThis.bench ??= []).push(a); };',
  '../shell/her/state': 'export const herLive = () => {}; export const herLiveLost = () => {};',
  '../api/screens': 'export const reportVisibility = async () => {};',
  '../speech/announce': 'export const announced = async (clip) => { (globalThis.announced ??= []).push(clip); };',
  './screen': 'export const screenToken = "t"; export const createReporting = () => ({ start() {}, stop() {} });',
  './feed': 'export const createFeed = (_open, handlers) => { globalThis.feedHandlers = handlers; return { up: () => false, open: () => {}, close: () => {} }; };',
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./live.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js' }));
  } }],
});
const code = built.outputFiles[0]!.text;
const { cueBenchPlayer, onBenchCue } = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)) as typeof Live;

type Heard = [number, number, Cue, CueBy];

function listen(): { heard: Heard[]; stop: () => void } {
  const heard: Heard[] = [];
  const stop = onBenchCue((bench, piece, cue, by) => heard.push([bench, piece, cue, by]));
  return { heard, stop };
}

test('a person cueing a player is heard by a listener with the bench, the piece, the cue as given, tagged person', () => {
  const { heard, stop } = listen();
  cueBenchPlayer(4, 9, { action: 'seek', seconds: 65 });
  stop();
  assert.deepEqual(heard, [[4, 9, { action: 'seek', seconds: 65 }, 'person']]);
});

test('a seek then a play are heard in the order given', () => {
  const { heard, stop } = listen();
  cueBenchPlayer(1, 2, { action: 'seek', seconds: 3.5 });
  cueBenchPlayer(1, 2, { action: 'play', seconds: null });
  stop();
  assert.deepEqual(heard.map((h) => [h[2].action, h[2].seconds, h[3]]), [['seek', 3.5, 'person'], ['play', null, 'person']]);
});

test('every listener hears it, and one that has stopped does not', () => {
  const a = listen();
  const b = listen();
  cueBenchPlayer(1, 1, { action: 'pause', seconds: null });
  a.stop();
  cueBenchPlayer(1, 1, { action: 'play', seconds: null });
  b.stop();
  assert.equal(a.heard.length, 1);
  assert.equal(b.heard.length, 2);
});

test('a cue with no listener is dropped, and one given before listening is never heard later', () => {
  cueBenchPlayer(1, 1, { action: 'play', seconds: null });
  const { heard, stop } = listen();
  stop();
  assert.deepEqual(heard, []);
});

test('unsubscribing twice is harmless', () => {
  const { stop } = listen();
  stop();
  stop();
  cueBenchPlayer(1, 1, { action: 'play', seconds: null });
});

interface FeedHandlers { heard(event: Record<string, unknown>): void }
const feedHandlers = (): FeedHandlers => Reflect.get(globalThis, 'feedHandlers') as FeedHandlers;

test('her cue over the feed is heard with the same arguments, tagged her', () => {
  const { heard, stop } = listen();
  feedHandlers().heard({ type: 'cue', bench_id: 3, piece_id: 5, action: 'seek', seconds: 12 });
  stop();
  assert.equal(heard.length, 1);
  const [bench, piece, cue, by] = heard[0]!;
  assert.deepEqual([bench, piece, cue.action, cue.seconds, by], [3, 5, 'seek', 12, 'her']);
});

test('a person and she are told apart by the tag alone, through one listener', () => {
  const { heard, stop } = listen();
  feedHandlers().heard({ type: 'cue', bench_id: 1, piece_id: 1, action: 'play', seconds: null });
  cueBenchPlayer(1, 1, { action: 'play', seconds: null });
  stop();
  assert.deepEqual(heard.map((h) => h[3]), ['her', 'person']);
});

test('a bench change on the feed is no cue', () => {
  const { heard, stop } = listen();
  feedHandlers().heard({ type: 'bench', bench_id: 1, seq: 2, by: null });
  stop();
  assert.deepEqual(heard, []);
});

test('a bench change on the feed hands the bench and who made it to her mark', () => {
  (globalThis as { bench?: unknown[] }).bench = [];
  feedHandlers().heard({ type: 'bench', bench_id: 7, seq: 2, by: 'her' });
  feedHandlers().heard({ type: 'bench', bench_id: 8, seq: 3, by: 'person' });
  assert.deepEqual((globalThis as { bench?: unknown[] }).bench, [[7, 'her'], [8, 'person']]);
});

test('an announcement the feed hears goes to the page\'s announcer with its clip', () => {
  const world = globalThis as unknown as { feedHandlers: { heard: (e: unknown) => void }; announced?: string[] };
  world.feedHandlers.heard({ type: 'announce', clip: 'tok-a' });
  world.feedHandlers.heard({ type: 'turn', thread: 'person:1:web' });
  assert.deepEqual(world.announced, ['tok-a']);
});
