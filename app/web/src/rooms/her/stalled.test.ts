import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Line } from './overlay.ts';
import { overlaid } from './overlay.ts';
import { endsOnHeldLine, stalledLine } from './stalled.ts';

const at = '2026-10-31T12:00:00Z';
const asked = (working?: boolean): Line => ({ key: 't1', author: 'person', text: 'is it raining', at, turn: 1, working });
const held: Line = { key: 't2', author: 'ashley', text: 'Let me check.', at, turn: 2, follows: true };
const answer: Line = { key: 't3', author: 'ashley', text: 'No rain today.', at, turn: 3 };
const none = { failed: null, mine: null, hers: null };

test('a conversation that ends on her held line with no work in flight has stalled', () => {
  assert.equal(endsOnHeldLine([asked(false), held]), true);
  assert.equal(endsOnHeldLine([asked(), held]), true);
});

test('a conversation with work in flight, an answer, or no held line has not stalled', () => {
  assert.equal(endsOnHeldLine([asked(true), held]), false);
  assert.equal(endsOnHeldLine([asked(false), held, answer]), false);
  assert.equal(endsOnHeldLine([asked(false)]), false);
  assert.equal(endsOnHeldLine([]), false);
});

test('a stalled turn marks the line owed an answer, and an answer that lands later clears it', () => {
  const lines = [asked(false), held];
  const marked = stalledLine(lines);
  assert.equal(marked?.missed, 'stalled');
  assert.equal(overlaid(lines, { ...none, failed: marked })[0]!.missed, 'stalled');
  assert.deepEqual(overlaid([...lines, answer], { ...none, failed: marked }).map((l) => l.missed), [undefined, undefined, undefined]);
});

test('nothing is marked when no line is owed', () => {
  assert.equal(stalledLine([asked(false), held, answer]), null);
});
