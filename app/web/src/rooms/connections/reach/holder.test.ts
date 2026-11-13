import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { holdsLine, stayReason } from './holder.ts';

const conn = (over: Partial<HouseholdConnection>): HouseholdConnection => ({
  id: 1, kind: 'x', label: '', base_url: '', added_by: { id: 1, household_id: 1, name: 'Alex', admin: true }, added_at: '', checked_at: '',
  personal: true, needs: null, scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true, ...over,
});
const kind = (holders: ('household' | 'person')[]) => ({ holders }) as unknown as ConnectionKindInfo;

test('a connection the payload lets move has no reason to stay', () => {
  assert.equal(stayReason(conn({ can_hand_over: true }), kind(['person', 'household'])), null);
  assert.equal(stayReason(conn({ personal: false, can_take_back: true }), kind(['person', 'household'])), null);
});

test('a kind with one possible holder says so', () => {
  assert.equal(stayReason(conn({}), kind(['person'])), 'This kind is always one person’s.');
  assert.equal(stayReason(conn({ personal: false }), kind(['household'])), 'This kind is always the household’s.');
});

test('one that could move but cannot for this person says who can', () => {
  assert.equal(stayReason(conn({ can_change: false }), kind(['person', 'household'])), 'Only Alex can change this.');
  assert.equal(stayReason(conn({}), kind(['person', 'household'])), 'Only the person who added it can take it back.');
});

test('who may use it follows who holds it', () => {
  assert.equal(holdsLine(conn({})), 'used only in chats that are Alex’s own');
  assert.equal(holdsLine(conn({ personal: false })), 'anyone at home can ask her to use it');
});
