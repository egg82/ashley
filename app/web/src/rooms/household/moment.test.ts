import assert from 'node:assert/strict';
import { test } from 'node:test';
import { momentIn, sayLine } from './moment.ts';

const thursday = new Date('2026-11-12T21:05:00Z');
const us = { locale: 'en-US', clock: '24h' as const };
const flat = (s: string | null) => s?.replace(/\s/g, ' ');

test('the local time in a zone is hours since its midnight, with its offset', () => {
  const m = momentIn(thursday, 'America/Denver', us);
  assert.equal(m?.text, '14:05');
  assert.equal(m?.offset, 'UTC-07:00');
  assert.ok(Math.abs((m?.hours ?? 0) - (14 + 5 / 60)) < 1e-9);
});

test('midnight is 0 and UTC says +00:00', () => {
  const m = momentIn(new Date('2026-11-13T00:00:00Z'), 'UTC', us);
  assert.equal(m?.hours, 0);
  assert.equal(m?.offset, 'UTC+00:00');
});

test('a zone the browser does not know has no time', () => {
  assert.equal(momentIn(thursday, 'Nowhere/Land', us), null);
  assert.equal(sayLine(thursday, 'Nowhere/Land', { ...us, unit_system: 'imperial' }), null);
});

test('she says it as the household writes: units, clock and weekday', () => {
  assert.equal(flat(sayLine(thursday, 'America/Denver', { ...us, unit_system: 'imperial' })), '72°F, 14:05, Thursday');
  assert.equal(flat(sayLine(thursday, 'America/Denver', { locale: 'en-US', clock: '12h', unit_system: 'metric' })), '22°C, 2:05 PM, Thursday');
});

test('the weekday is the zone\'s, not the browser\'s', () => {
  assert.match(sayLine(thursday, 'Asia/Tokyo', { ...us, unit_system: 'metric' }) ?? '', /Friday$/);
});
