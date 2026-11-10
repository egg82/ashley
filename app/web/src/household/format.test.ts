import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hour, locale, writing } from './format.ts';

const at = new Date(Date.UTC(2026, 10, 10, 8, 5));
const time = (w: Parameters<typeof locale>[0]) =>
  at.toLocaleTimeString(locale(w), { hour: hour(w), minute: '2-digit', timeZone: 'UTC' });

test('a new household writes en-US on a 24-hour clock until it says otherwise', () => {
  assert.deepEqual(writing.value, { locale: 'en-US', clock: '24h' });
  assert.equal(locale(), 'en-US-u-hc-h23');
});

test('the clock follows the household, not its locale', () => {
  assert.equal(time({ locale: 'en-US', clock: '24h' }), '08:05');
  assert.equal(time({ locale: 'en-US', clock: '12h' }), '8:05 AM');
  assert.equal(time({ locale: 'en-GB', clock: '12h' }), '8:05 am');
  assert.equal(time({ locale: 'en-GB', clock: '24h' }), '08:05');
});

test('dates are written in the household locale', () => {
  const day = (l: string) => at.toLocaleDateString(locale({ locale: l, clock: '24h' }), { day: 'numeric', month: 'long', timeZone: 'UTC' });
  assert.equal(day('en-US'), 'November 10');
  assert.equal(day('en-GB'), '10 November');
});
