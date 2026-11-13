import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hourLabel, windowLine } from './quietLine.ts';

test('an hour is written as the household writes the clock', () => {
  assert.equal(hourLabel(7, '24h'), '07:00');
  assert.equal(hourLabel(0, '12h'), '12 AM');
  assert.equal(hourLabel(12, '12h'), '12 PM');
  assert.equal(hourLabel(22, '12h'), '10 PM');
});

test('a window reads as its two hours and the zone it is in', () => {
  assert.equal(windowLine({ start: 22, end: 7, timezone: 'America/Denver' }, '12h'), '10 PM to 7 AM (America/Denver)');
});
