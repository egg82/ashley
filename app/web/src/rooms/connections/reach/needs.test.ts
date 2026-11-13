import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { needOf, scopeLabel } from './needs.ts';

const conn = (over: Partial<HouseholdConnection>): HouseholdConnection => ({
  id: 1, kind: 'gitlab', label: '', base_url: '', added_by: { id: 1, household_id: 1, name: 'Sam', admin: true }, added_at: '', checked_at: '',
  personal: true, needs: null, scopes: [], missing_scopes: [], resources: [], can_hand_over: false, can_take_back: false, can_change: true, ...over,
});
const kind = (over: Partial<ConnectionKindInfo>): ConnectionKindInfo => ({
  name: 'gitlab', title: 'GitLab', what: '', blurb: '', connected: '', removed: '', holders: ['person'], most: 1, picks_catalogue_provider: false, takes_address: true,
  address_placeholder: '', secret_field: 'token', secret_label: '', secret_noun: 'token', connect: 'pasted', set_up: true, has_settings: false, ...over,
});

test('nothing flagged asks nothing of anyone', () => {
  assert.equal(needOf(conn({}), kind({})), null);
});

test('a pasted kind that was refused is fixed by pasting a new secret', () => {
  const n = needOf(conn({ needs: 'reconnect' }), kind({ secret_noun: 'token' }));
  assert.equal(n?.fix, 'replace');
  assert.equal(n?.action, 'Paste a new token');
  assert.equal(n?.title, 'Reconnect GitLab');
  assert.match(n?.says ?? '', /Sam’s GitLab/);
});

test('a consent-screen kind that was refused, or lacks scopes, is fixed through the consent screen', () => {
  const google = kind({ name: 'google', title: 'Google', connect: 'oauth' });
  assert.equal(needOf(conn({ kind: 'google', needs: 'reconnect' }), google)?.fix, 'oauth');
  const scoped = needOf(conn({ kind: 'google', missing_scopes: ['https://www.googleapis.com/auth/calendar.readonly'] }), google);
  assert.equal(scoped?.fix, 'oauth');
  assert.equal(scoped?.action, 'Allow in Google');
  assert.match(scoped?.says ?? '', /read the calendar/);
});

test('a Bridge login that was signed out asks to log in', () => {
  assert.equal(needOf(conn({ kind: 'proton', needs: 'login' }), kind({ name: 'proton', title: 'Proton Mail', connect: 'bridge' }))?.fix, 'login');
});

test('a scope not in the table is named by the last part of its address', () => {
  assert.equal(scopeLabel('https://example.test/auth/things.read'), 'things.read');
});
