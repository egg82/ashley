import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Household } from '../../api/types';
import { changedLabels, draftOf, requestOf } from './draft.ts';

const h: Household = { id: 1, name: 'H', timezone: 'America/Denver', profile: 'p', profile_limit: 100, locale: 'en-US',
  unit_system: 'imperial', clock: '24h', latitude: null, longitude: null };

test('an unset position is two blank boxes', () => {
  const d = draftOf(h);
  assert.equal(d.latitude, '');
  assert.equal(d.longitude, '');
});

test('each change is named once, latitude and longitude as one position', () => {
  const was = draftOf(h);
  assert.deepEqual(changedLabels(was, was), []);
  assert.deepEqual(changedLabels({ ...was, latitude: '1', longitude: '2', clock: '12h' }, was), ['clock', 'position']);
  assert.deepEqual(changedLabels({ ...was, profile: 'q', timezone: 'UTC' }, was), ['time zone', 'notebook']);
});

test('the request carries the position as numbers and the text trimmed', () => {
  const was = draftOf(h);
  assert.deepEqual(requestOf({ ...was, timezone: ' UTC ', latitude: '39.5', longitude: '-104' }),
    { timezone: 'UTC', profile: 'p', locale: 'en-US', unit_system: 'imperial', clock: '24h', latitude: 39.5, longitude: -104 });
});

test('half a position or one out of range is no request', () => {
  const was = draftOf(h);
  assert.equal(requestOf({ ...was, latitude: '1' }), 'incomplete');
  assert.equal(requestOf({ ...was, latitude: '91', longitude: '0' }), 'range');
});
