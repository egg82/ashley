import assert from 'node:assert/strict';
import { test } from 'node:test';
import { connectOutcomeOf } from './connectOutcome.ts';

test('every outcome the callback names is read, and nothing else', () => {
  for (const o of ['connected', 'cancelled', 'wrong_person', 'refused', 'label_taken', 'too_many', 'unavailable', 'failed']) {
    assert.equal(connectOutcomeOf(o), o);
  }
  assert.equal(connectOutcomeOf('linked'), null);
  assert.equal(connectOutcomeOf(undefined), null);
});
