import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Line } from './overlay.ts';
import { failedLine, missedFor, overlaid } from './overlay.ts';

const at = '2026-11-08T12:00:00Z';
const asked = (working?: boolean): Line => ({ key: 't1', author: 'person', text: 'plan thanksgiving', at, turn: 1, working });
const answer: Line = { key: 't2', author: 'ashley', text: 'Here is the plan.', at, turn: 2 };
const none = { failed: null, mine: null, hers: null };

test('each reason a turn has no reply marks the line owed an answer with its own status', () => {
  assert.equal(missedFor('unavailable'), 'unreachable');
  assert.equal(missedFor('refused'), 'refused');
  assert.equal(missedFor('retrying'), 'retrying');
  assert.equal(missedFor('unfinished'), 'unfinished');
  assert.equal(missedFor('too_big'), 'too_big');
});

test('a turn too big for one reply shows its own status once the work is gone', () => {
  const marked = failedLine([asked(false)], 'too_big');
  assert.equal(overlaid([asked(false)], { ...none, failed: marked })[0]!.missed, 'too_big');
});

test('a turn kept to try again shows the status even while the kept work is in flight', () => {
  const marked = failedLine([asked(true)], 'retrying');
  assert.equal(overlaid([asked(true)], { ...none, failed: marked })[0]!.missed, 'retrying');
});

test('a turn that could not finish shows its status once the work is gone', () => {
  const marked = failedLine([asked(false)], 'unfinished');
  assert.equal(overlaid([asked(false)], { ...none, failed: marked })[0]!.missed, 'unfinished');
});

test('a later real reply replaces the status', () => {
  const marked = failedLine([asked(true)], 'retrying');
  assert.deepEqual(overlaid([asked(false), answer], { ...none, failed: marked }).map((l) => l.missed), [undefined, undefined]);
});

test('no status is shown when no line is owed', () => {
  assert.equal(failedLine([asked(false), answer], 'retrying'), null);
});
