import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { standingOf } from './standing.ts';

const conn = (id: number, over: Partial<HouseholdConnection>): HouseholdConnection => ({
  id, kind: 'sure', label: '', base_url: '', added_by: null, added_at: '', checked_at: '', personal: false, needs: null, scopes: [],
  missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true, ...over,
});
const kinds = [{ name: 'sure', title: 'Sure', connect: 'pasted', secret_noun: 'key' }] as unknown as ConnectionKindInfo[];

test('nothing connected says so and counts nothing', () => {
  const s = standingOf([], kinds);
  assert.equal(s.strong, 'Nothing is connected yet.');
  assert.equal(s.total, 0);
});

test('nothing flagged', () => {
  const s = standingOf([conn(1, {}), conn(2, { personal: true })], kinds);
  assert.deepEqual([s.needYou, s.notFlagged, s.personal], [0, 2, 1]);
  assert.equal(s.strong, 'Nothing is asking for you.');
});

test('one needing a person leads, and the sentence agrees with the count', () => {
  const s = standingOf([conn(1, { needs: 'reconnect' }), conn(2, {})], kinds);
  assert.deepEqual([s.needYou, s.notFlagged], [1, 1]);
  assert.equal(s.strong, '1 needs you.');
  const two = standingOf([conn(1, { needs: 'reconnect' }), conn(2, { missing_scopes: ['openid'] })], kinds);
  assert.equal(two.strong, '2 need you.');
  assert.equal(two.rest, '');
});
