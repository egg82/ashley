import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { holderOf, hostOf, sentenceOf } from './sentence.ts';

const sam = { id: 1, household_id: 1, name: 'Sam', admin: true };
const conn = (over: Partial<HouseholdConnection>): HouseholdConnection => ({
  id: 1, kind: 'sure', label: '', base_url: 'https://money.example/path', added_by: sam, added_at: '', checked_at: '', personal: false,
  needs: null, scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true, ...over,
});
const kind = (over: Partial<ConnectionKindInfo>): ConnectionKindInfo => ({
  name: 'sure', title: 'Sure', what: 'finances', blurb: '', connected: '', removed: '', holders: ['household'], most: 1, picks_catalogue_provider: false, takes_address: true,
  address_placeholder: '', secret_field: 'api_key', secret_label: '', secret_noun: 'key', connect: 'pasted', set_up: true, has_settings: false, ...over,
});
const text = (s: ReturnType<typeof sentenceOf>) => `${s.before}${s.name}${s.after}`;

test('a household connection reads as the household’s, with the host of its address under it', () => {
  const s = sentenceOf(conn({}), kind({}));
  assert.equal(text(s), 'She reads the household’s accounts in Sure');
  assert.equal(s.address, 'money.example');
});

test('a personal connection is its holder’s own', () => {
  const s = sentenceOf(conn({ kind: 'gitlab', personal: true }), kind({ name: 'gitlab', title: 'GitLab' }));
  assert.equal(text(s), 'She reads Sam’s repositories on GitLab');
});

test('a kind with no address says its one mailbox, and a mail bridge counts its mailboxes', () => {
  const box = { ref: 'a@x', kind: 'mailbox' as const, name: 'a@x', shared: false };
  const google = sentenceOf(conn({ kind: 'google', personal: true, resources: [box] }), kind({ name: 'google', title: 'Google', takes_address: false }));
  assert.equal(text(google), 'She works in Sam’s Google account');
  assert.equal(google.address, 'a@x');
  const proton = sentenceOf(conn({ kind: 'proton', personal: true, resources: [box, { ...box, ref: 'b@x', name: 'b@x' }] }), kind({ name: 'proton', title: 'Proton Mail', takes_address: false }));
  assert.equal(text(proton), 'She reads 2 Proton Mail mailboxes through the bridge');
  assert.equal(proton.address, null);
});

test('a label the person gave is the name, and an unknown kind still reads as a sentence', () => {
  const s = sentenceOf(conn({ kind: 'later', label: 'Spare', personal: true }), kind({ name: 'later', title: 'Later' }));
  assert.equal(text(s), 'She reaches Spare for Sam');
});

test('who holds it, and an address with a pinned certificate or a bridge scheme', () => {
  assert.equal(holderOf(conn({ personal: true, added_by: null })), 'one person');
  assert.equal(holderOf(conn({})), 'the household');
  assert.equal(hostOf('https://10.0.0.9:7843#sha256=ab'), '10.0.0.9:7843');
  assert.equal(hostOf('bridge://proton'), 'proton');
});
