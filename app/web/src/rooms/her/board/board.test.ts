import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WorkItem } from '../../../api/types.ts';
import { causeLine } from './cause.ts';
import { laneName, lanes } from './lanes.ts';
import { offers, undoneWord, undoResult, whyNot } from './offers.ts';

let next = 1;
function item(over: Partial<WorkItem> = {}): WorkItem {
  return { kind: 'errand', id: next++, title: 'thing', state: 'running', lane: 'doing', at: '2026-11-27T09:00:00Z', can_tap: false, can_undo: false, ...over };
}

test('lanes come in reading order, what waits on the person first, and empty lanes are left out', () => {
  const items = [
    item({ lane: 'done_untold', state: 'done' }),
    item({ lane: 'on_her_own', kind: 'action', state: 'done' }),
    item({ lane: 'doing' }),
    item({ lane: 'waiting', state: 'waiting_on_you' }),
  ];
  assert.deepEqual(lanes(items).map((l) => l.lane), ['waiting', 'doing', 'on_her_own', 'done_untold']);
  assert.deepEqual(lanes(items).map((l) => l.name), ['Waiting on you', "She's doing", 'On her own', 'Done, not yet told']);
  assert.deepEqual(lanes([]), []);
});

test('within a lane the server\'s order is kept', () => {
  const a = item({ title: 'a' });
  const b = item({ title: 'b' });
  const c = item({ title: 'c' });
  assert.deepEqual(lanes([b, a, c])[0]!.items.map((i) => i.title), ['b', 'a', 'c']);
});

test('a lane the client does not know still shows, after the known ones, under a name from its key', () => {
  const quiet = item({ lane: 'kept_quiet' as WorkItem['lane'] });
  const odd = item({ lane: 'saved_for_later' as WorkItem['lane'] });
  const shown = lanes([odd, item({ lane: 'waiting', state: 'waiting_on_you' }), quiet]);
  assert.deepEqual(shown.map((l) => l.lane), ['waiting', 'kept_quiet', 'saved_for_later']);
  assert.equal(shown[1]!.name, 'Kept quiet');
  assert.equal(shown[2]!.name, 'Saved for later');
  assert.equal(laneName(''), 'Other');
});

test('a tappable proposal offers Agree; any other proposal a reply where it was made', () => {
  assert.deepEqual(offers(item({ kind: 'proposal', id: 7, can_tap: true, conversation_id: 3 }), 3), [{ kind: 'agree', proposal: 7 }]);
  assert.deepEqual(offers(item({ kind: 'proposal', conversation_id: 3 }), 3), [{ kind: 'reply', here: true }]);
  assert.deepEqual(offers(item({ kind: 'proposal', conversation_id: 4 }), 3), [{ kind: 'reply', here: false }]);
  assert.deepEqual(offers(item({ kind: 'proposal', conversation_id: null }), 3), []);
});

test('a live or stopped watch offers Cancel, a finished one nothing', () => {
  assert.deepEqual(offers(item({ kind: 'watch', id: 9, state: 'running' }), null), [{ kind: 'cancel', watch: 9 }]);
  assert.deepEqual(offers(item({ kind: 'watch', id: 9, state: 'stopped' }), null), [{ kind: 'cancel', watch: 9 }]);
  assert.deepEqual(offers(item({ kind: 'watch', state: 'done' }), null), []);
});

test('an action offers Undo only while the server says it can be undone and it was not', () => {
  const undo = { kind: 'house_delete' as const, ref: 'x', within: 'automation' };
  assert.deepEqual(offers(item({ kind: 'action', id: 5, undo, can_undo: true }), null), [{ kind: 'undo', action: 5 }]);
  assert.deepEqual(offers(item({ kind: 'action', undo, can_undo: false }), null), []);
  assert.deepEqual(offers(item({ kind: 'action', undo, can_undo: true, undone: { at: 'x', how: 'undoing' } }), null), []);
  assert.deepEqual(offers(item({ kind: 'errand' }), null), []);
  assert.deepEqual(offers(item({ kind: 'bench', state: 'open' }), null), []);
});

test('a taken Undo reads how it stands, and a delete sent to a proposal says it waits on the person', () => {
  assert.equal(undoneWord(item({ kind: 'action' })), null);
  assert.equal(undoneWord(item({ kind: 'action', undone: { at: 'x', how: 'undone' } })), 'Undone');
  assert.equal(undoneWord(item({ kind: 'action', undone: { at: 'x', how: 'waiting_on_you' } })), 'Undo waits on your yes');
  assert.match(undoResult('waiting_on_you'), /waits on your yes/);
  assert.match(undoResult('gone'), /Already gone/);
});

test('a refusal names its reason; anything unreached says so', () => {
  assert.equal(whyNot(409, 'already_undone'), 'Already undone.');
  assert.equal(whyNot(409, 'refused'), "She couldn't undo it.");
  assert.match(whyNot(409, 'something_new'), /didn't work/);
  assert.match(whyNot(undefined, undefined), /Couldn't reach her/);
  assert.match(whyNot(503, 'unavailable'), /Couldn't reach her/);
});

test('a cause is named by the item it points at when that is on the board, else by its kind', () => {
  const watch = item({ kind: 'watch', id: 40, title: 'Watching for the pump to ship' });
  const bench = item({ kind: 'bench', id: 40, title: 'Balcony watering', state: 'open' });
  const did = (cause: NonNullable<WorkItem['cause']>) => item({ kind: 'action', lane: 'on_her_own', cause });
  assert.equal(causeLine(did({ kind: 'watch', id: 40 }), [bench, watch]), 'Watching for the pump to ship');
  assert.equal(causeLine(did({ kind: 'bench', id: 40 }), [watch, bench]), 'Balcony watering');
  assert.equal(causeLine(did({ kind: 'watch', id: 41 }), [watch]), 'a watch');
  assert.equal(causeLine(did({ kind: 'reminder', id: 40 }), [watch]), 'a reminder', 'a reminder id is not a watch id');
  assert.match(causeLine(did({ kind: 'turn', id: 1 }), [])!, /outside the household/);
  assert.equal(causeLine(item(), [watch]), null);
});
