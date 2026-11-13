import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WireFact, WireReceipts } from '../../api/types';
import { factRows, keyOf, whyNotSet } from './facts.ts';

const form: WireFact = { bench_id: 3, piece_id: 2, name: 'form', label: 'The lanyard', value: 'flat strap', option_values: ['flat strap', 'round cord'] };
const colour: WireFact = { bench_id: 3, piece_id: 2, name: 'colour', label: 'Colour', value: 'red', option_values: [] };
const shown: WireReceipts = { ran: [], held: [], proposal_id: null, choice_rows: [form, colour] };

test('each choice is a row in the order she set them, hers picked until the person taps another', () => {
  assert.deepEqual(factRows(shown, new Map()).map((r) => [r.fact.label, r.picked, r.options]),
    [['The lanyard', 'flat strap', ['flat strap', 'round cord']], ['Colour', 'red', []]]);
  const tapped = new Map([[keyOf(form), 'round cord']]);
  assert.deepEqual(factRows(shown, tapped).map((r) => r.picked), ['round cord', 'red']);
});

test('a turn that showed no choices has no rows', () => {
  assert.deepEqual(factRows({ ...shown, choice_rows: [] }, new Map()), []);
  assert.deepEqual(factRows(null, new Map()), []);
});

test('a refused tap says what happened by its status, and anything else is a plain failure', () => {
  assert.match(whyNotSet(409), /changed/);
  assert.match(whyNotSet(404), /isn't on the bench/);
  assert.equal(whyNotSet(500), whyNotSet(undefined));
});
