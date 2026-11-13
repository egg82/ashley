import assert from 'node:assert/strict';
import { test } from 'node:test';
import { writing } from '../household/format.ts';
import { ofDay, whenOf } from './agenda.ts';

test('a time is written on the household clock, and all-day says so', () => {
  writing.value = { locale: 'en-US', clock: '24h' };
  assert.equal(whenOf('16:30'), '16:30');
  assert.equal(whenOf('05:00'), '05:00');
  writing.value = { locale: 'en-US', clock: '12h' };
  assert.equal(whenOf('16:30'), '4:30 PM');
  assert.equal(whenOf(null), 'All day');
});

test('the events of one day keep the order the glance gave them', () => {
  const events = [{ title: 'a', day: 'today', time: null }, { title: 'b', day: 'tomorrow', time: '09:00' }, { title: 'c', day: 'today', time: '10:00' }] as const;
  assert.deepEqual(ofDay(events, 'today').map((e) => e.title), ['a', 'c']);
  assert.deepEqual(ofDay(events, 'tomorrow').map((e) => e.title), ['b']);
});
