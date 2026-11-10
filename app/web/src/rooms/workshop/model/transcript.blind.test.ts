import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lineAt } from './transcript.ts';

/** A small seeded generator, so a failure reproduces. */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function sortedStarts(next: () => number): number[] {
  const n = Math.floor(next() * 12);
  const out: number[] = [];
  let t = Math.floor(next() * 3);
  for (let i = 0; i < n; i++) {
    out.push(t);
    t += next() < 0.2 ? 0 : Math.round(next() * 40) / 4;
  }
  return out;
}

/** The contract stated plainly: the later of the lines with the latest start at or before `seconds`. */
function expected(starts: readonly number[], seconds: number): number {
  let best = -1;
  starts.forEach((s, i) => {
    if (s <= seconds && (best === -1 || s >= starts[best]!)) best = i;
  });
  return best;
}

test('over sorted starts it agrees with the stated rule at, between and around every start', () => {
  const next = rng(7);
  for (let round = 0; round < 300; round++) {
    const starts = sortedStarts(next);
    const probes = [-1, 0, 1e9, ...starts, ...starts.map((s) => s - 0.001), ...starts.map((s) => s + 0.001), next() * 100];
    for (const t of probes) assert.equal(lineAt(starts, t), expected(starts, t), `${JSON.stringify(starts)} at ${t}`);
  }
});

test('over sorted starts the line never moves backwards as the time advances', () => {
  const next = rng(11);
  for (let round = 0; round < 200; round++) {
    const starts = sortedStarts(next);
    let last = -1;
    for (let t = -1; t < 120; t += 0.5) {
      const at = lineAt(starts, t);
      assert.ok(at >= last, `${JSON.stringify(starts)} at ${t}`);
      last = at;
    }
  }
});

test('a result is -1 or an index whose start is at or before the time', () => {
  const next = rng(3);
  for (let round = 0; round < 200; round++) {
    const starts = sortedStarts(next);
    const t = next() * 60;
    const at = lineAt(starts, t);
    assert.ok(at === -1 || (at >= 0 && at < starts.length && starts[at]! <= t));
    if (at === -1) assert.ok(starts.every((s) => s > t));
  }
});

test('a time before the first start, or no lines at all, is -1', () => {
  assert.equal(lineAt([], 0), -1);
  assert.equal(lineAt([], 1e6), -1);
  assert.equal(lineAt([5], 4.999), -1);
  assert.equal(lineAt([5], -3), -1);
});

test('a time exactly at a start is that line, and any time past the last is the last line', () => {
  assert.equal(lineAt([0, 10, 20], 10), 1);
  assert.equal(lineAt([0, 10, 20], 20), 2);
  assert.equal(lineAt([0, 10, 20], 1e12), 2);
  assert.equal(lineAt([0], 0), 0);
});

test('lines starting together give the later line', () => {
  assert.equal(lineAt([0, 5, 5, 5, 9], 5), 3);
  assert.equal(lineAt([0, 5, 5, 5, 9], 8), 3);
  assert.equal(lineAt([2, 2], 2), 1);
});

test('starts out of order: the latest start at or before the time wins, not the last one scanned', () => {
  assert.equal(lineAt([0, 10, 4], 5), 2);
  assert.equal(lineAt([0, 10, 4], 12), 1);
  assert.equal(lineAt([9, 1, 5], 6), 2);
});

test('the starts are not changed', () => {
  const starts = [0, 3, 6];
  lineAt(starts, 4);
  assert.deepEqual(starts, [0, 3, 6]);
});

test('a start before zero is still a start: the line is spoken from then on', () => {
  assert.equal(lineAt([-5, 3], -2), 0);
  assert.equal(lineAt([-5, 3], -6), -1);
  assert.equal(lineAt([-1], 0), 0);
});
