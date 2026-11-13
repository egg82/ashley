import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WorkItem } from '../../api/types';
import { KIND_WORD, STATE_WORD, waiting, where } from './workRows.ts';

const item = (kind: WorkItem['kind'], state: WorkItem['state'], id = 7): WorkItem => ({ kind, id, title: 't', state, at: '2026-11-13T10:00:00Z' });

test('a bench links into the workshop room and an open-ended errand to her reminders; a one-shot errand has no link', () => {
  assert.equal(where(item('bench', 'open', 12)), '/workshop/12');
  assert.equal(where(item('open_errand', 'running')), '/memory?tab=reminders');
  assert.equal(where(item('errand', 'running')), null);
});

test('every state and kind the server can send has a word, and the words differ', () => {
  const states = Object.keys(STATE_WORD);
  assert.deepEqual(states.sort(), ['done', 'open', 'running', 'stopped', 'waiting_on_you']);
  assert.equal(new Set(Object.values(STATE_WORD)).size, states.length);
  assert.equal(STATE_WORD.waiting_on_you, 'Waiting on you');
  assert.equal(new Set(Object.values(KIND_WORD)).size, 3);
});

test('only items waiting on the person count as waiting', () => {
  const rows = [item('bench', 'waiting_on_you'), item('errand', 'running'), item('open_errand', 'waiting_on_you'), item('errand', 'done')];
  assert.equal(waiting(rows), 2);
  assert.equal(waiting([]), 0);
});
