// Contract 18 to 22, blind: voice.ts is the one owner of playback on a page. A tagged send opens a window in that tab
// only; her new voiced turns play in it, in order and once each; tapping record stops her before the microphone opens;
// the audio is primed synchronously inside the record tap; a refused play shows a play control and a missing voice shows
// nothing; the window closes on her first non-follows turn, after voice_s, or on the next send.
import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { bind, hers, install, load, person, playing, settle, tapPlay, tick, uninstall, type Kind, type Loaded,
         type World } from './voiceBlindFakes.ts';

afterEach(() => uninstall());

async function page(kind: Kind = 'desktop', limit?: number): Promise<{ w: World; m: Loaded }> {
  const w = install(kind);
  if (limit !== undefined) w.limits.voice_s = limit;
  const m = await load();
  bind(m);
  return { w, m };
}

const seen = (...ids: number[]): ReadonlySet<number> => new Set(ids);
const notAllowed = () => new DOMException('play() failed: user gesture required', 'NotAllowedError');

test('c18: a tagged send opens the window and a voiced turn new since then plays, once', async () => {
  const { w, m } = await page();
  m.voice.primeVoice();
  m.voice.awaitVoice(seen(1, 2));
  m.voice.offer([person(1), hers(2, false), person(3), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [4]);
  m.voice.offer([person(1), hers(2, false), person(3), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [4], 'the same turn offered again does not play again');
});

test('c18: a voiced turn that was already shown at the send does not play', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1, 2));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(w.played, []);
});

test('c18: a turn without a voice does not play, and a turn of the persons does not either', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), { ...person(5), voiced: true }, hers(6, false)]);
  await settle();
  assert.deepEqual(w.played, []);
});

test('c18: a tab that sent no tagged message has no window and never plays', async () => {
  const { w, m } = await page();
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(w.played, []);
  assert.deepEqual(w.fetched, [], 'nothing was even fetched');
});

test('c18: two tabs read the same turn and only the one that sent it plays', async () => {
  const sender = await page();
  const reader = await load();
  bind(reader);
  sender.m.voice.awaitVoice(seen(1));
  const turns = [person(1), hers(2)];
  sender.m.voice.offer(turns);
  reader.voice.offer(turns);
  await settle();
  assert.deepEqual(sender.w.played, [2], 'one play for the page that opened the window, none for the other');
});

test('c18: a turn after a typed send never plays', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.stopVoice();
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(w.played, []);
});

test('c19: tapping record while she plays stops her before the microphone opens', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(w.played, [2]);
  const t = m.talk(async () => ({ text: 'ok' }), () => {}, () => {});
  t.start();
  await settle();
  const stopped = w.log.indexOf('audio.pause');
  const opened = w.log.indexOf('mic.open');
  assert.ok(stopped >= 0 && opened >= 0, 'she was paused and the microphone opened');
  assert.ok(stopped < opened, 'paused first');
  assert.equal(playing(m), null);
  assert.equal(w.audios.some((a) => !a.paused), false);
});

test('c19: stopping pauses and drops the audio, and with nothing playing is harmless', async () => {
  const { w, m } = await page();
  m.voice.stopVoice();
  assert.equal(playing(m), null);
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(playing(m), { turn: 2, phase: 'playing' });
  m.voice.stopVoice();
  assert.equal(playing(m), null);
  assert.ok(w.audios.every((a) => a.paused));
});

for (const kind of ['desktop', 'android', 'ios'] as const) {
  test(`c20: the record tap primes the audio synchronously, before any await (${kind})`, async () => {
    const { w, m } = await page(kind);
    const t = m.talk(async () => ({ text: 'ok' }), () => {}, () => {});
    t.start();
    assert.ok(w.log.includes('ctx.resume'), 'the audio context was resumed inside the tap');
    assert.ok(w.log.includes('ctx.silent'), 'a silent buffer was played inside the tap');
    assert.equal(w.contexts.length, 1);
    assert.ok(w.audios.length >= 1, 'the audio element exists before the microphone does');
    assert.equal(w.log.includes('mic.open'), false, 'control: nothing after the first await has run yet');
    await settle();
    assert.ok(w.log.indexOf('ctx.resume') < w.log.indexOf('mic.open'));
  });
}

test('c20: priming twice keeps one audio context and one element', async () => {
  const { w, m } = await page();
  m.voice.primeVoice();
  m.voice.primeVoice();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.equal(w.contexts.length, 1);
  assert.equal(new Set(w.audios).size, 1);
  assert.deepEqual(w.played, [2]);
});

test('c20: the primed element is the one that plays her voice', async () => {
  const { w, m } = await page();
  m.voice.primeVoice();
  const element = w.audios[0];
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.ok(element && element.src.includes('2') && !element.paused, 'one element for both unlocking and playing');
});

test('c21: a play the browser refuses shows a play control on that turn, and tapping it plays', async () => {
  const { w, m } = await page();
  w.rejectPlay = notAllowed();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(playing(m), { turn: 2, phase: 'blocked' });
  assert.deepEqual(w.played, []);
  tapPlay(m, 2);
  await settle();
  assert.deepEqual(w.played, [2]);
  assert.deepEqual(playing(m), { turn: 2, phase: 'playing' });
});

test('c21: a refused play is not retried on its own and is not swallowed into silence', async () => {
  const { w, m } = await page();
  w.rejectPlay = notAllowed();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2)]);
  await settle();
  m.voice.offer([person(1), hers(2)]);
  await settle();
  assert.deepEqual(w.played, []);
  assert.deepEqual(playing(m), { turn: 2, phase: 'blocked' });
});

for (const status of [404, 503]) {
  test(`c21: a ${status} for her voice shows nothing beyond her text and no error`, async () => {
    const { w, m } = await page();
    w.status.set(2, status);
    m.voice.awaitVoice(seen(1));
    m.voice.offer([person(1), hers(2)]);
    await settle();
    assert.equal(playing(m), null);
    assert.deepEqual(w.played, []);
    assert.deepEqual(w.problems, [], 'no console error and no unhandled rejection');
  });

  test(`c21: a held line whose voice is ${status} does not keep her answer from playing`, async () => {
    const { w, m } = await page();
    w.status.set(3, status);
    m.voice.awaitVoice(seen(1));
    m.voice.offer([person(1), hers(3, true, true), hers(4)]);
    await settle();
    assert.deepEqual(w.played, [4]);
    assert.deepEqual(w.problems, []);
  });
}

test('c22: a held line and its answer both play, in order, the line finishing first', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(3, true, true), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [3]);
  assert.equal(w.pauses, 0, 'the held line was not cut off for the answer');
  w.audios.find((a) => !a.paused)!.finish();
  await settle();
  assert.deepEqual(w.played, [3, 4]);
});

test('c22: the held line arrives first and the answer in a later read: both play, once each', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(3, true, true)]);
  await settle();
  w.audios.find((a) => !a.paused)!.finish();
  await settle();
  m.voice.offer([person(1), hers(3, true, true), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [3, 4]);
  assert.equal(playing(m) && (playing(m) as { turn: number }).turn, 4);
});

test('c22: the window closes on her first non-follows turn', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(4)]);
  await settle();
  w.audios.find((a) => !a.paused)!.finish();
  m.voice.offer([person(1), hers(4), hers(9)]);
  await settle();
  assert.deepEqual(w.played, [4], 'a later voiced turn of hers (a wake, say) is not this exchange');
  assert.equal(playing(m), null);
});

test('c22: a non-follows turn without a voice also closes the window', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(4, false)]);
  await settle();
  m.voice.offer([person(1), hers(4, false), hers(9)]);
  await settle();
  assert.deepEqual(w.played, []);
});

test('c22: the window closes after voice_s, by the served value', async () => {
  for (const [limit, before, after] of [[120, 119_000, 121_000], [30, 29_000, 31_000]] as const) {
    uninstall();
    const early = await page('desktop', limit);
    early.m.voice.awaitVoice(seen(1));
    await settle();
    tick(before);
    early.m.voice.offer([person(1), hers(2)]);
    await settle();
    assert.deepEqual(early.w.played, [2], `still open at ${before} ms of a ${limit} s window`);
    uninstall();
    const late = await page('desktop', limit);
    late.m.voice.awaitVoice(seen(1));
    await settle();
    tick(after);
    late.m.voice.offer([person(1), hers(2)]);
    await settle();
    assert.deepEqual(late.w.played, [], `closed at ${after} ms of a ${limit} s window`);
  }
});

test('c22: the next send closes the window and opens its own', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.awaitVoice(seen(1, 2, 3, 4));
  m.voice.offer([person(1), hers(2), person(3), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [], 'what was new at the first send is old at the second');
  m.voice.offer([person(1), hers(2), person(3), hers(4), person(5), hers(6)]);
  await settle();
  assert.deepEqual(w.played, [6]);
});

test('c22: a send while she is talking cuts her off', async () => {
  const { w, m } = await page();
  m.voice.awaitVoice(seen(1));
  m.voice.offer([person(1), hers(2, true, true)]);
  await settle();
  assert.deepEqual(w.played, [2]);
  m.voice.stopVoice();
  m.voice.awaitVoice(seen(1, 2, 3));
  m.voice.offer([person(1), hers(2, true, true), person(3), hers(4)]);
  await settle();
  assert.deepEqual(w.played, [2, 4]);
  assert.ok(w.pauses >= 1);
});
