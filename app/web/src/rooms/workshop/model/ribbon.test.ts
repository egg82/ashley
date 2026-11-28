import assert from 'node:assert/strict';
import { test } from 'node:test';
import { barLine, ribbonOf, type TalkLine } from './ribbon.ts';

const you = (n: number, text = `you ${n}`): TalkLine => ({ key: `t${n}`, author: 'person', text, turn: n });
const her = (n: number, text = `her ${n}`): TalkLine => ({ key: `t${n}`, author: 'ashley', text, turn: n });
const onBench = (id: number) => id !== 99;

test('one dot per line in the order said, her answers aimed at the first piece still on the bench', () => {
  const touched = new Map([[2, [99, 5, 6]], [4, [99]]]);
  const { dots, earlier } = ribbonOf([you(1), her(2), you(3), her(4)], touched, onBench);
  assert.deepEqual(dots.map((d) => [d.key, d.who, d.piece]), [['t1', 'you', null], ['t2', 'her', 5], ['t3', 'you', null], ['t4', 'her', null]]);
  assert.equal(earlier, 0);
});

test('the ribbon draws the latest lines and counts the rest', () => {
  const lines = Array.from({ length: 15 }, (_, i) => (i % 2 ? her(i + 1) : you(i + 1)));
  const { dots, earlier } = ribbonOf(lines, new Map(), onBench, 12);
  assert.equal(dots.length, 12);
  assert.equal(earlier, 3);
  assert.equal(dots[0]!.key, 't4');
  assert.equal(dots.at(-1)!.key, 't15');
});

test('household lines take no dot, and a line that did not reach her is marked', () => {
  const lines: TalkLine[] = [{ key: 'h', author: 'household', text: 'x' }, { ...you(1), missed: { why: 'down' } }];
  const { dots } = ribbonOf(lines, new Map(), onBench);
  assert.deepEqual(dots.map((d) => [d.key, d.missed]), [['t1', true]]);
});

test('the voice bar shows her new answer, and the piece on the bench it is about', () => {
  const touched = new Map([[2, [99, 5]], [4, [99]]]);
  assert.deepEqual(barLine([you(1), her(2)], touched, onBench, new Set()), { line: her(2), piece: 5 }, 'its words are the callout on piece 5');
  assert.deepEqual(barLine([you(3), her(4)], touched, onBench, new Set()), { line: her(4), piece: null }, 'its piece is gone from the bench');
  assert.deepEqual(barLine([you(3), her(6)], touched, onBench, new Set()), { line: her(6), piece: null });
  assert.equal(barLine([you(3), her(6)], touched, onBench, new Set([6])), null, 'an answer from before the page opened');
  assert.equal(barLine([her(6), you(7)], touched, onBench, new Set()), null, 'the person spoke since');
  assert.equal(barLine([her(6, '')], touched, onBench, new Set()), null, 'an empty answer');
});
