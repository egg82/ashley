import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ProtonAccount } from '../../api/types';
import { nextOf, SAID, sentOf, stateOf } from './protonSteps.ts';

const account = (over: Partial<ProtonAccount>): ProtonAccount => ({
  connection_id: 1, state: 'connected', addresses: [], syncing: false, sync_progress: null, ...over,
});

test('Bridge asking for a code or the second password is the next step, and a connected login is done', () => {
  assert.deepEqual(nextOf({ step: 'two_factor', connection_id: null, addresses: [] }), { to: 'ask', ask: 'two_factor' });
  assert.deepEqual(nextOf({ step: 'mailbox_password', connection_id: null, addresses: [] }), { to: 'ask', ask: 'mailbox_password' });
  assert.deepEqual(nextOf({ step: 'connected', connection_id: 4, addresses: ['a@proton.test'] }), { to: 'done' });
});

test('a human check is the next step with its page, and without a page it is a failure to say', () => {
  const url = 'https://verify.proton.me/?token=t';
  assert.deepEqual(nextOf({ step: 'human_verification', connection_id: null, addresses: [], verification_url: url }), { to: 'verify', url });
  assert.deepEqual(nextOf({ step: 'human_verification', connection_id: null, addresses: [] }), { to: 'said', said: 'failed' });
});

test('a password goes to Bridge exactly as typed, spaces and all; only a code loses the spaces around it', () => {
  assert.equal(sentOf('credentials', '  pass word '), '  pass word ');
  assert.equal(sentOf('mailbox_password', ' x '), ' x ');
  assert.equal(sentOf('two_factor', ' 123456 '), '123456');
});

test('a refusal is said and never taken for the step to ask, so a refused password leaves its words on the form', () => {
  for (const reason of [
    'credentials', 'code', 'mailbox_password', 'paid_plan', 'connection', 'aborted', 'verification', 'security_key',
    'label_taken', 'too_many', 'other',
  ] as const) {
    assert.deepEqual(nextOf({ reason, detail: '' }), { to: 'said', said: reason });
    assert.ok(SAID[reason].length > 10);
  }
  assert.ok(SAID.unavailable && SAID.failed);
});

test('an account says whether it is synced, how far it has got, or why it cannot be used', () => {
  assert.equal(stateOf(undefined), null);
  assert.equal(stateOf(account({})), 'Up to date');
  assert.equal(stateOf(account({ syncing: true })), 'Copying mail');
  assert.equal(stateOf(account({ syncing: true, sync_progress: 0.426 })), 'Copying mail, 43%');
  assert.match(stateOf(account({ state: 'signed_out' })) ?? '', /log in again/);
  assert.equal(stateOf(account({ state: 'locked', syncing: true })), 'Locked');
});
