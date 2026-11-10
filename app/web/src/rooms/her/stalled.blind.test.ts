import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Line } from './overlay.ts';
import { STALL_MS, endsOnHeldLine, stalledLine } from './stalled.ts';

const at = '2026-10-31T12:00:00Z';
const person = (n: number, working?: boolean): Line => ({ key: `p${n}`, author: 'person', text: `ask ${n}`, at, turn: n, working });
const held = (n: number): Line => ({ key: `h${n}`, author: 'ashley', text: 'Let me check.', at, turn: n, follows: true });
const said = (n: number): Line => ({ key: `a${n}`, author: 'ashley', text: 'Done.', at, turn: n });

test('the wait before a quiet conversation shows unfinished is twenty seconds', () => {
  assert.equal(STALL_MS, 20_000);
});

test('several held lines in a row still end on a held line', () => {
  assert.equal(endsOnHeldLine([person(1, false), held(2), held(3)]), true);
});

test('a later message of the person after the held line is not a conversation sitting on her held line', () => {
  assert.equal(endsOnHeldLine([person(1, false), held(2), person(3, false)]), false);
});

test('work in flight on the line owed an answer keeps it from stalling, whichever held lines trail it', () => {
  assert.equal(endsOnHeldLine([person(1, true), held(2), held(3)]), false);
});

test('only the line owed an answer counts for work in flight, not an earlier answered one', () => {
  assert.equal(endsOnHeldLine([person(1, true), held(2), said(3), person(4, false), held(5)]), true);
});

test('a held line with no person line before it is not owed anything', () => {
  assert.equal(endsOnHeldLine([held(1)]), false);
  assert.equal(stalledLine([held(1)]), null);
});

test('the marked line is the person line owed an answer, otherwise unchanged', () => {
  const owed = person(4, false);
  const marked = stalledLine([person(1, false), held(2), said(3), owed, held(5)]);
  assert.deepEqual(marked, { ...owed, missed: 'stalled' });
});

test('the line given is not mutated by marking it', () => {
  const owed = person(1, false);
  const lines = [owed, held(2)];
  stalledLine(lines);
  assert.equal(owed.missed, undefined);
  assert.equal(lines.length, 2);
});
