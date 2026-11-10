import assert from 'node:assert/strict';
import { test } from 'node:test';
import { whyNotAgreed } from './agreeWhy.ts';

test('each refusal code says its own reason', () => {
  const said = ['gone', 'expired', 'not_yours'].map((code) => whyNotAgreed(409, code));
  assert.equal(new Set(said).size, 3);
  assert.ok(said.every((s) => !s.includes("didn't go through")));
});

test('an unknown code, a 503 or no status is a failure to reach her', () => {
  for (const [status, code] of [[409, 'other'], [409, undefined], [503, 'unavailable'], [undefined, undefined]] as const) {
    assert.match(whyNotAgreed(status, code), /didn't go through/);
  }
});
