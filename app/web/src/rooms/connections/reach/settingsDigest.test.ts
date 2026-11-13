import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SettingChange, SettingEntry, SettingInfo } from '../../../api/types';
import { digestOf, historyOf } from './settingsDigest.ts';

const alex = { id: 1, household_id: 1, name: 'Alex', admin: true };
const info = (key: string, decides: SettingInfo['decides']): SettingInfo => ({ key, decides, field: { type: 'entity_list', domains: [] } });
const change = (id: number, key: string, by: typeof alex | null, at: string): SettingChange => ({ id, key, edited_by: by, changed_at: at });
const settings = [info('note', 'plain'), info('reads', 'read'), info('consequential_entities', 'tier')];
const values: SettingEntry[] = [
  { key: 'consequential_entities', ids: ['a', 'b'], per_action: [] },
  { key: 'reads', ids: [], per_action: [{ action: 'x', ids: ['c'] }, { action: 'y', ids: ['d', 'e'] }] },
];

test('what decides her behaviour leads, preferences follow, each in the order the kind declared', () => {
  const rows = digestOf(settings, values, []);
  assert.deepEqual(rows.map((r) => r.key), ['reads', 'consequential_entities', 'note']);
  assert.deepEqual(rows.map((r) => r.judging), [true, true, false]);
});

test('each counts what it holds, per-action ids included, and a setting with no value holds none', () => {
  const rows = digestOf(settings, values, []);
  assert.deepEqual(rows.map((r) => r.count), [3, 2, 0]);
});

test('who last changed each is the newest change to its key; none recorded is null, a departed person has no name', () => {
  const changes = [change(3, 'reads', alex, '2026-11-09T21:12:00Z'), change(2, 'consequential_entities', null, '2026-11-05T10:00:00Z'), change(1, 'reads', alex, '2026-11-01T10:00:00Z')];
  const rows = digestOf(settings, values, changes);
  assert.deepEqual(rows[0]!.by, { name: 'Alex' });
  assert.equal(rows[0]!.at, '2026-11-09T21:12:00Z');
  assert.deepEqual(rows[1]!.by, { name: null });
  assert.equal(rows[2]!.by, null);
  assert.equal(rows[2]!.at, null);
});

test('the history keeps the server’s order and names the setting in words', () => {
  const lines = historyOf([change(2, 'consequential_entities', alex, 'b'), change(1, 'unknown_key', null, 'a')]);
  assert.deepEqual(lines.map((l) => [l.who, l.what]), [['Alex', 'things that need your word'], [null, 'unknown key']]);
});
