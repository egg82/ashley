import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SettingChange } from '../../../api/types';
import { historyOf } from './settingsHistory.ts';

const sam = { id: 1, household_id: 1, name: 'Sam', admin: true };
const change = (id: number, key: string, by: typeof sam | null, at: string): SettingChange => ({ id, key, edited_by: by, changed_at: at });
test('the history keeps the server’s order and names the setting in words', () => {
  const lines = historyOf([change(2, 'consequential_entities', sam, 'b'), change(1, 'unknown_key', null, 'a')]);
  assert.deepEqual(lines.map((l) => [l.who, l.what]), [['Sam', 'things that need your word'], [null, 'unknown key']]);
});
