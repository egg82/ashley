import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SettingEntry } from '../../../api/types';
import { draftOf, entriesOf, idsOf, LIST, same, toggled, withIds } from './draft.ts';

const stored: SettingEntry[] = [
  { key: 'reads', ids: ['script.a'], per_action: [] },
  { key: 'household_reads', ids: [], per_action: [{ action: 'todo.get_items', ids: ['todo.inbox'] }] },
];

test('what was read is what would be sent', () => {
  assert.deepEqual(entriesOf(draftOf(stored)), stored);
});

test('a setting with nothing picked is left out of the request', () => {
  const emptied = withIds(draftOf(stored), 'reads', LIST, []);
  assert.deepEqual(entriesOf(emptied).map((e) => e.key), ['household_reads']);
});

test('an action with nothing picked is left out of an entity-per-action entry', () => {
  const draft = withIds(draftOf(stored), 'household_reads', 'todo.other', []);
  assert.deepEqual(entriesOf(draft), stored);
});

test('ids are read from a list or from an action, and are empty for a key never set', () => {
  const draft = draftOf(stored);
  assert.deepEqual(idsOf(draft, 'reads'), ['script.a']);
  assert.deepEqual(idsOf(draft, 'household_reads', 'todo.get_items'), ['todo.inbox']);
  assert.deepEqual(idsOf(draft, 'consequential_entities'), []);
});

test('toggling adds an id once and takes it out again', () => {
  assert.deepEqual(toggled(['a.b'], 'c.d'), ['a.b', 'c.d']);
  assert.deepEqual(toggled(['a.b', 'c.d'], 'a.b'), ['c.d']);
});

test('a draft is the same as what was read until something is picked', () => {
  const draft = draftOf(stored);
  assert.ok(same(draft, draftOf(stored)));
  assert.ok(!same(draft, withIds(draft, 'reads', LIST, ['script.a', 'script.b'])));
  assert.ok(same(withIds(draft, 'consequential_entities', LIST, []), draft), 'an empty list is no entry');
});
