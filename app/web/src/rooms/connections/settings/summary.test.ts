import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { SettingEntry } from '../../../api/types';
import { summaryOf } from './summary.ts';

const ids = (key: string, list: string[]): SettingEntry => ({ key, ids: list, per_action: [] });

test('an empty house says so in each part', () => {
  assert.equal(summaryOf([]), 'no lists, no look-ups, nothing that needs your word');
});

test('lists, look-ups and things that need her word are counted from what is stored', () => {
  const values: SettingEntry[] = [
    { key: 'household_reads', ids: [], per_action: [{ action: 'todo.get_items', ids: ['todo.a', 'todo.b', 'todo.c'] }] },
    ids('reads', ['script.x', 'script.y', 'script.z', 'script.w']),
    ids('service_reads', ['script.x', 'weather.get_forecasts']),
    ids('consequential_entities', ['switch.rack']),
  ];
  assert.equal(summaryOf(values), '3 lists, 5 look-ups, 1 that needs your word');
});

test('a trust stored for a script with no look-up beside it is not a look-up', () => {
  assert.equal(summaryOf([ids('service_reads', ['script.x'])]), 'no lists, no look-ups, nothing that needs your word');
});
