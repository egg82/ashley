import assert from 'node:assert/strict';
import { beforeEach, mock, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import type * as Announce from './announce.ts';

// announce.ts imports extensionless siblings, so it is bundled as the client's own build does and loaded from that
// bundle, with the api client replaced by a stand-in whose lines `lines` scripts, and the browser's audio and page
// visibility by the fakes below.
const stubs: Record<string, string> = {
  '../api/speech': `export const clipVoiceUrl = (clip) => '/clip/' + clip;
    export const getClipLine = async (clip) => {
      const line = globalThis.lines[clip];
      if (line === undefined) throw new Error('404');
      return { line };
    };`,
};
const built = await build({
  entryPoints: [fileURLToPath(new URL('./announce.ts', import.meta.url))], bundle: true, write: false, format: 'esm',
  platform: 'node', logLevel: 'silent',
  plugins: [{ name: 'stubs', setup(b) {
    b.onResolve({ filter: /.*/ }, (args) => (args.path in stubs ? { path: args.path, namespace: 'stub' } : undefined));
    b.onLoad({ filter: /.*/, namespace: 'stub' }, (args) => ({ contents: stubs[args.path], loader: 'js' }));
  } }],
});
const code = built.outputFiles[0]!.text;
const announce = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)) as typeof Announce;

class FakeAudio {
  static made: FakeAudio[] = [];
  static refuse: 'none' | 'blocked' | 'other' = 'none';
  src = '';
  played: string[] = [];
  paused = 0;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeAudio.made.push(this);
  }
  play(): Promise<void> {
    this.played.push(this.src);
    if (FakeAudio.refuse === 'blocked') return Promise.reject(new DOMException('no', 'NotAllowedError'));
    return FakeAudio.refuse === 'other' ? Promise.reject(new DOMException('no', 'AbortError')) : Promise.resolve();
  }
  pause(): void {
    this.paused++;
  }
}
const page = { visibilityState: 'visible' as 'visible' | 'hidden' };
const world = globalThis as unknown as { lines: Record<string, string> };
Object.assign(globalThis, { Audio: FakeAudio, document: page });

const settle = () => new Promise((resolve) => setImmediate(resolve));
const played = () => FakeAudio.made.flatMap((a) => a.played);

beforeEach(() => {
  announce.dismiss();
  FakeAudio.made.forEach((a) => (a.played = []));
  FakeAudio.refuse = 'none';
  page.visibilityState = 'visible';
  world.lines = { a: 'Someone is at the front door.', b: 'The door is open.' };
});

test('a page in the foreground shows the line and plays the clip, and the line leaves a while after it ends', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    await announce.announced('a');
    assert.deepEqual(announce.announcement.value, { clip: 'a', line: 'Someone is at the front door.', phase: 'playing' });
    assert.deepEqual(played(), ['/clip/a']);
    FakeAudio.made[0]!.onended!();
    assert.equal(announce.announcement.value?.phase, 'said');
    mock.timers.tick(announce.LINGER_MS - 1);
    assert.equal(announce.announcement.value?.clip, 'a', 'the line stays until the linger is over');
    mock.timers.tick(1);
    assert.equal(announce.announcement.value, null);
  } finally {
    mock.timers.reset();
  }
});

test('a page in the background takes nothing, and a clip whose line cannot be read plays nothing', async () => {
  page.visibilityState = 'hidden';
  await announce.announced('a');
  page.visibilityState = 'visible';
  await announce.announced('gone');
  assert.equal(announce.announcement.value, null);
  assert.deepEqual(played(), []);
});

test('a refused play shows a play control, and the tap plays it', async () => {
  FakeAudio.refuse = 'blocked';
  await announce.announced('a');
  await settle();
  assert.equal(announce.announcement.value?.phase, 'blocked');
  FakeAudio.refuse = 'none';
  announce.playAnnouncement();
  assert.equal(announce.announcement.value?.phase, 'playing');
  assert.deepEqual(played(), ['/clip/a', '/clip/a']);
});

test('a play that fails another way leaves the line as said, not a play control', async () => {
  FakeAudio.refuse = 'other';
  await announce.announced('a');
  await settle();
  assert.equal(announce.announcement.value?.phase, 'said');
});

test('a newer announcement replaces the one playing, whose end no longer touches it; dismissing stops the voice', async () => {
  await announce.announced('a');
  const element = FakeAudio.made[0]!;
  const endOfA = element.onended!;
  await announce.announced('b');
  assert.deepEqual(announce.announcement.value, { clip: 'b', line: 'The door is open.', phase: 'playing' });
  endOfA();
  assert.equal(announce.announcement.value?.phase, 'playing', "a's end is not b's");
  const paused = element.paused;
  announce.dismiss();
  assert.equal(announce.announcement.value, null);
  assert.equal(element.paused, paused + 1);
});
