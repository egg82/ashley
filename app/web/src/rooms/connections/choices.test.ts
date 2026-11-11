import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection, LinkedAccount } from '../../api/types';
import { addable, matching, whose } from './choices.ts';

function kind(name: string, title: string, what: string, holders: ConnectionKindInfo['holders']): ConnectionKindInfo {
  return {
    name, title, what, blurb: `Let her read ${what}.`, connected: '', removed: '', holders, most: 1, takes_address: true,
    address_placeholder: '', secret_field: 'token', secret_label: 'Token', secret_noun: 'token', connect: 'pasted', set_up: true, has_settings: false,
  };
}

const sure = kind('sure', 'Sure', 'finances', ['household']);
const gitlab = kind('gitlab', 'GitLab', 'your code', ['person']);
const google = kind('google', 'Google', 'your Google account', ['household', 'person']);
const held: HouseholdConnection = { id: 1, label: '', kind: 'sure', base_url: '', added_by: null, added_at: '', checked_at: '', personal: false, scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true };
const discord: LinkedAccount = { id: 1, system: 'discord', handle: 'a', unlinkable: true };

test('a connected kind is not offered again', () => {
  assert.deepEqual(addable([sure, gitlab], [held], [discord]).map((c) => c.id), ['gitlab']);
});

test('a kind is offered again while its owner holds fewer than it allows', () => {
  const several = { ...sure, most: 2 };
  const second = { ...held, id: 2, label: 'work' };
  assert.deepEqual(addable([several], [held], [discord]).map((c) => c.id), ['sure']);
  assert.deepEqual(addable([several], [held, second], [discord]).map((c) => c.id), []);
});

test('Discord is offered until it is linked, first', () => {
  assert.deepEqual(addable([sure], [], []).map((c) => c.id), ['discord', 'sure']);
  assert.deepEqual(addable([sure], [], [discord]).map((c) => c.id), ['sure']);
});

test('search needs every word, in the title, what, description or the Yours / Household tag', () => {
  const all = addable([sure, gitlab], [], [discord]);
  assert.deepEqual(matching(all, 'sure').map((c) => c.id), ['sure']);
  assert.deepEqual(matching(all, 'CODE git').map((c) => c.id), ['gitlab']);
  assert.deepEqual(matching(all, 'household').map((c) => c.id), ['sure']);
  assert.deepEqual(matching(all, 'yours').map((c) => c.id), ['gitlab']);
  assert.deepEqual(matching(all, 'sure code'), []);
  assert.equal(matching(all, '  ').length, 2);
});

test('a kind is whose it may be held by, and a kind either may hold answers to both words', () => {
  assert.deepEqual([sure, gitlab, google].map(whose), ['household', 'yours', 'either']);
  const all = addable([sure, gitlab, google], [], [discord]);
  assert.deepEqual(matching(all, 'household').map((c) => c.id), ['sure', 'google']);
  assert.deepEqual(matching(all, 'yours').map((c) => c.id), ['gitlab', 'google']);
});
