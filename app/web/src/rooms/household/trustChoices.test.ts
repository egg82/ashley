import assert from 'node:assert/strict';
import { test } from 'node:test';
import { lockedLine, picksWith } from './trustChoices.ts';

const rows = [
  { kind: 'reminders', label: 'Reminders', value: 'act' as const, locked: null },
  { kind: 'lists', label: 'Lists', value: 'offer' as const, locked: null },
  { kind: 'money', label: 'Money', value: 'offer' as const, locked: 'asks' as const },
];

test('a save carries every row, with only the changed kind different', () => {
  assert.deepEqual(picksWith(rows, 'reminders', 'offer'), [
    { kind: 'reminders', value: 'offer' },
    { kind: 'lists', value: 'offer' },
    { kind: 'money', value: 'offer' },
  ]);
  assert.deepEqual(picksWith(rows, 'lists', 'act')[1], { kind: 'lists', value: 'act' });
});

test('only a locked row says why it cannot change', () => {
  assert.equal(lockedLine(rows[0]!), null);
  assert.match(lockedLine(rows[2]!)!, /always asks/);
  assert.match(lockedLine({ ...rows[2]!, locked: 'irreversible' })!, /can't be undone/);
});
