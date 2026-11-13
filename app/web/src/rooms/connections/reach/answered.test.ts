import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { HouseholdConnection } from '../../../api/types';
import { ageShort, ageText, bandOf, metaOf } from './answered.ts';

const NOW = Date.parse('2026-11-13T08:00:00Z');
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;
const day = (iso: string) => iso.slice(5, 10);
const conn = (over: Partial<HouseholdConnection>): HouseholdConnection => ({
  id: 1, kind: 'sure', label: '', base_url: '', added_by: { id: 1, household_id: 1, name: 'Alex', admin: true }, added_at: ago(9 * DAY),
  checked_at: ago(14 * MIN), personal: false, needs: null, scopes: [], missing_scopes: [], resources: [], can_hand_over: false,
  can_take_back: false, can_change: true, ...over,
});

test('ages read in the unit that fits, singular at one', () => {
  assert.equal(ageText(ago(14 * MIN), NOW), '14 minutes ago');
  assert.equal(ageText(ago(HOUR), NOW), '1 hour ago');
  assert.equal(ageText(ago(26 * HOUR), NOW), '1 day ago');
  assert.equal(ageText(ago(9 * DAY), NOW), '9 days ago');
  assert.equal(ageText(ago(5_000), NOW), 'just now');
  assert.equal(ageShort(ago(14 * MIN), NOW), '14 min ago');
  assert.equal(ageShort(ago(2 * HOUR), NOW), '2 h ago');
  assert.equal(ageShort(ago(11 * DAY), NOW), '11 d ago');
});

test('the bands split at a day and a week', () => {
  assert.equal(bandOf(ago(23 * HOUR), NOW), 'today');
  assert.equal(bandOf(ago(25 * HOUR), NOW), 'week');
  assert.equal(bandOf(ago(6 * DAY), NOW), 'week');
  assert.equal(bandOf(ago(8 * DAY), NOW), 'older');
});

test('a connection that has answered since it was added says when', () => {
  const m = metaOf(conn({}), NOW, day);
  assert.equal(m.answeredSince, true);
  assert.equal(m.answered, 'answered 14 minutes ago');
  assert.match(m.added, /^added by Alex, /);
  assert.deepEqual(m.holder, { personal: false, text: 'household' });
});

test('checked only when added says so, and one nobody added was carried over from her setup', () => {
  const when = ago(2 * DAY);
  const m = metaOf(conn({ added_at: when, checked_at: when, added_by: null }), NOW, day);
  assert.equal(m.answeredSince, false);
  assert.equal(m.answered, 'answered once, 2 days ago');
  assert.match(m.added, /^carried over from her setup, /);
});

test('a personal connection names its holder', () => {
  assert.deepEqual(metaOf(conn({ personal: true }), NOW, day).holder, { personal: true, text: 'Alex alone' });
});
