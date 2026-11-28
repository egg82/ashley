import assert from 'node:assert/strict';
import { test } from 'node:test';
import { badgeText, FRESH_MS, isFresh, linesByPiece, nextFold, noteSeen, type HerLine } from './herLines.ts';

const line = (turn: number, at: number, pieces: number[]): HerLine => ({ turn, at, text: `line ${turn}`, pieces });

test('each piece gets the lines that touched it, latest first, once per line', () => {
  const by = linesByPiece([line(1, 100, [3]), line(2, 300, [3, 4]), line(3, 200, [4, 9])], (id) => (id === 9 ? 4 : id));
  assert.deepEqual(by.get(3)!.map((l) => l.turn), [2, 1]);
  assert.deepEqual(by.get(4)!.map((l) => l.turn), [2, 3], 'piece 9 is drawn in 4\'s card and counts once');
  assert.equal(by.get(9), undefined);
});

test('on the first read a line counts from when she said it, later ones from when they were seen', () => {
  const now = 1_000_000;
  const first = noteSeen(new Map(), [line(1, now - 60_000, [1])], now, true);
  assert.equal(first.get(1), now - 60_000);
  assert.ok(!isFresh(first.get(1), now), 'an old line is a badge on reload');
  const later = noteSeen(first, [line(1, now - 60_000, [1]), line(2, now - 999_999, [1])], now + 5, false);
  assert.equal(later.get(1), now - 60_000, 'a seen line keeps its start');
  assert.equal(later.get(2), now + 5, 'a skewed server clock does not hide a new line');
  assert.ok(isFresh(later.get(2), now + 5));
  const ahead = noteSeen(new Map(), [line(3, now + 50_000, [1])], now, true);
  assert.equal(ahead.get(3), now, 'a line stamped in the future counts from now');
});

test('a line folds into the badge after FRESH_MS', () => {
  assert.ok(isFresh(0, FRESH_MS - 1));
  assert.ok(!isFresh(0, FRESH_MS));
  assert.ok(!isFresh(undefined, 0));
});

test('the next fold is when the youngest fresh line ages out', () => {
  const seen = new Map([[1, 0], [2, 5000], [3, -50_000]]);
  assert.equal(nextFold(seen, 1000), FRESH_MS - 1000);
  assert.equal(nextFold(seen, FRESH_MS + 1), 5000 - 1);
  assert.equal(nextFold(seen, 100_000), null);
});

test('the badge counts lines', () => {
  assert.equal(badgeText(1), '1 line');
  assert.equal(badgeText(3), '3 lines');
});
