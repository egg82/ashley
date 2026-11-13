import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { HouseholdConnection } from '../../../api/types';
import { groupsOf } from './groups.ts';

const conn = (id: number, kind: string): HouseholdConnection => ({
  id, kind, label: '', base_url: '', added_by: null, added_at: '', checked_at: '', personal: false, needs: null,
  scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true,
});

test('connections group by what they give her, in the room’s order, and empty groups are left out', () => {
  const groups = groupsOf([conn(1, 'openai'), conn(2, 'sure'), conn(3, 'proton'), conn(4, 'github')]);
  assert.deepEqual(groups.map((g) => g.id), ['money', 'code', 'mail', 'voice']);
  assert.deepEqual(groups.map((g) => g.items.map((c) => c.id)), [[2], [4], [3], [1]]);
});

test('a kind no group names is still shown, last', () => {
  const groups = groupsOf([conn(1, 'sure'), conn(2, 'someday')]);
  assert.deepEqual(groups.map((g) => g.id), ['money', 'other']);
  assert.equal(groups[1]!.items[0]!.id, 2);
});

test('nothing connected is no groups', () => {
  assert.deepEqual(groupsOf([]), []);
});
