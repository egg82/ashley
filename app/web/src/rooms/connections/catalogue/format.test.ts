import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cadence, connectedCount, orderProviders, perMtok, priceWord, tokenCount, yesNo } from './format.ts';

const p = (provider: string, name: string, has_connection: boolean | null) =>
  ({ provider, name, api: null, model_count: 1, overridden_count: 0, has_connection });

test('an unknown value is null, a listed zero is a price', () => {
  assert.equal(perMtok(null), null);
  assert.equal(perMtok(0), '$0');
  assert.equal(perMtok(3), '$3');
  assert.equal(perMtok(0.075), '$0.075');
  assert.equal(tokenCount(null), null);
  assert.equal(tokenCount(200_000), '200K');
  assert.equal(yesNo(null), null);
  assert.equal(yesNo(false), 'no');
});

test('only a priced model has no price word', () => {
  assert.equal(priceWord('priced'), null);
  assert.deepEqual((['unpriced', 'listed_zero', 'free', 'local'] as const).map(priceWord), ['unpriced', 'listed at $0', 'free', 'local, no cost']);
});

test('connected providers come first, then by name; the search keeps name or id', () => {
  const all = [p('b', 'Bravo', false), p('a', 'Alpha', false), p('z', 'Zed', true), p('u', 'Unknown', null)];
  assert.deepEqual(orderProviders(all, '').map((x) => x.provider), ['z', 'a', 'b', 'u']);
  assert.deepEqual(orderProviders(all, ' AL ').map((x) => x.provider), ['a']);
  assert.deepEqual(orderProviders(all, 'o').map((x) => x.provider), ['b', 'u']);
});

test('a connected count is unknown when no provider could be told', () => {
  assert.equal(connectedCount([p('a', 'A', null)]), null);
  assert.equal(connectedCount([p('a', 'A', false), p('b', 'B', true)]), 1);
  assert.equal(connectedCount([p('a', 'A', false)]), 0);
});

test('the cadence names its unit', () => {
  assert.equal(cadence(21600), 'every 6 h');
  assert.equal(cadence(600), 'every 10 min');
});
