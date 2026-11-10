import assert from 'node:assert/strict';
import { test } from 'node:test';
import { degrees, parsePlace } from './place.ts';

test('both boxes blank is no location', () => {
  assert.deepEqual(parsePlace('', '  '), { latitude: null, longitude: null });
});

test('two numbers within range are a location, spaces and signs allowed', () => {
  assert.deepEqual(parsePlace(' 51.5072 ', '-0.1276'), { latitude: 51.5072, longitude: -0.1276 });
  assert.deepEqual(parsePlace('-90', '180'), { latitude: -90, longitude: 180 });
});

test('one box without the other is incomplete', () => {
  assert.equal(parsePlace('51.5', ''), 'incomplete');
  assert.equal(parsePlace('', '-0.12'), 'incomplete');
});

test('words, non-finite numbers and degrees past the poles or the date line are out of range', () => {
  const bad: [string, string][] = [['north', '0'], ['0', 'NaN'], ['Infinity', '0'], ['90.1', '0'], ['0', '-180.5']];
  for (const [lat, lon] of bad) {
    assert.equal(parsePlace(lat, lon), 'range', `${lat}, ${lon}`);
  }
});

test('a stored coordinate shows as typed and none shows blank', () => {
  assert.equal(degrees(null), '');
  assert.equal(degrees(51.5072), '51.5072');
  assert.deepEqual(parsePlace(degrees(51.5072), degrees(-0.1276)), { latitude: 51.5072, longitude: -0.1276 });
});
