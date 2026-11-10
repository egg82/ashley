import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Quiet, WINDOW_MS, type QuietTuning } from './quiet.ts';

const RATE = 16000;
const TUNING: QuietTuning = { speechMs: 300, silenceMs: 700, threshold: 0.02 };
const BLOCK = 128;

function block(loud: boolean): Float32Array {
  return new Float32Array(BLOCK).fill(loud ? 0.1 : 0.001);
}

/** Feeds `ms` of loud or quiet samples in 128-sample blocks; answers whether the detector fired at any point. */
function feed(q: Quiet, loud: boolean, ms: number): boolean {
  let fired = false;
  for (let n = 0; n < (ms / 1000) * RATE; n += BLOCK) fired = q.push(block(loud)) || fired;
  return fired;
}

test('speech and then enough quiet ends the utterance', () => {
  const q = new Quiet(TUNING, RATE);
  assert.equal(feed(q, true, 1000), false);
  assert.equal(feed(q, false, 600), false);
  assert.equal(feed(q, false, 200), true);
});

test('quiet alone never ends it', () => {
  assert.equal(feed(new Quiet(TUNING, RATE), false, 20000), false);
});

test('speech shorter than speechMs followed by quiet does not end it', () => {
  const q = new Quiet(TUNING, RATE);
  feed(q, true, 200);
  assert.equal(feed(q, false, 5000), false);
});

test('speech of exactly speechMs is enough', () => {
  const q = new Quiet(TUNING, RATE);
  feed(q, true, 300);
  assert.equal(feed(q, false, 700 + WINDOW_MS), true);
});

test('a pause shorter than silenceMs mid-speech does not end it, and restarts the count', () => {
  const q = new Quiet(TUNING, RATE);
  feed(q, true, 500);
  assert.equal(feed(q, false, 600), false);
  feed(q, true, 100);
  assert.equal(feed(q, false, 600), false);
  assert.equal(feed(q, false, 200), true);
});

test('a window exactly at the threshold is speech', () => {
  const q = new Quiet({ ...TUNING, threshold: 0.25 }, RATE);
  const at = new Float32Array(BLOCK).fill(0.25);
  for (let n = 0; n < (500 / 1000) * RATE; n += BLOCK) q.push(at);
  assert.equal(feed(q, false, 800), true);
});

test('block size does not change the verdict', () => {
  const q = new Quiet(TUNING, RATE);
  const speech = new Float32Array(RATE).fill(0.1);
  q.push(speech);
  const quiet = new Float32Array(RATE).fill(0);
  assert.equal(q.push(quiet), true);
});

test('once ended it stays ended', () => {
  const q = new Quiet(TUNING, RATE);
  feed(q, true, 1000);
  feed(q, false, 1000);
  assert.equal(feed(q, true, 100), true);
});
