import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { HouseholdConnection } from '../../../api/types';
import { teethOf, teethSummary } from './teeth.ts';

const box = (name: string, shared: boolean) => ({ ref: name, kind: 'mailbox' as const, name, shared });
const conn = (resources: HouseholdConnection['resources']): HouseholdConnection => ({
  id: 1, kind: 'proton', label: '', base_url: '', added_by: { id: 1, household_id: 1, name: 'Sam', admin: true }, added_at: '', checked_at: '',
  personal: true, needs: null, scopes: [], missing_scopes: [], resources, can_hand_over: false, can_take_back: false, can_change: true,
});

test('one tooth per resource, in the order the server gave', () => {
  const teeth = teethOf(conn([box('a', true), box('b', false)]));
  assert.deepEqual(teeth.map((t) => [t.name, t.shared]), [['a', true], ['b', false]]);
});

test('the summary counts shared and kept, and leaves out a side with none', () => {
  assert.equal(teethSummary(conn([box('a', true), box('b', false), box('c', false)])), '1 shared with the household, 2 kept to Sam');
  assert.equal(teethSummary(conn([box('a', false)])), '1 kept to Sam');
  assert.equal(teethSummary(conn([box('a', true)])), '1 shared with the household');
  assert.equal(teethSummary(conn([])), '');
});
