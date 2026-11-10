import assert from 'node:assert/strict';
import { test } from 'node:test';
import { card, items, note, receipt, wire } from './receiptsBlindSupport.ts';

const lamp = receipt('Changed something in the house', 'Changed something in the house (action: light.turn_on)', 'You asked for it.');
const mail = receipt('Moved an email to a folder', 'Moved an email to a folder (folder: archive)', null);
const held1 = receipt('Changed something in the house', 'Changed something in the house (action: light.turn_on, entity: light.porch)', 'It is not in what you said.');
const held2 = receipt('Moved an email to a folder', 'Moved an email to a folder (folder: archive, subject: a whole subject line)');

test('the done note is one quiet line of the headlines, in order', () => {
  assert.equal(note(wire([lamp, mail])), 'Done: Changed something in the house, Moved an email to a folder');
});

test('the done note carries no detail, no why and no proposal', () => {
  const line = note(wire([lamp], [held1], 7));
  assert.ok(line !== null && !line.includes('(action') && !line.includes('You asked for it.') && !line.includes('7'));
  assert.ok(!line.includes('\n'));
});

test('there is no done note when nothing was done, or when the turn has no receipts', () => {
  assert.equal(note(wire([], [held1], 3)), null);
  assert.equal(note(null), null);
  assert.equal(note(undefined), null);
});

test('one tap opens each done change with its detail and why', () => {
  assert.deepEqual(items(wire([lamp, mail], [held1], 3)), [lamp, mail]);
  assert.deepEqual(items(null), []);
});

test('the Agree card shows every held call by headline and in full, in order, without a tap', () => {
  const got = card(wire([lamp], [held1, held2], 7), 7);
  assert.ok(got !== null);
  assert.deepEqual(got.items, [held1, held2]);
  assert.equal(got.items[1]!.detail, 'Moved an email to a folder (folder: archive, subject: a whole subject line)');
});

test('a long summary is shown whole, never cut', () => {
  const long = receipt('Moved an email to a folder', `Moved an email to a folder (subject: ${'x'.repeat(4000)})`);
  const got = card(wire([], [long], 4), 4);
  assert.equal(got!.items[0]!.detail, long.detail);
});

test('the card has no Agree to offer for a turn the page gives no agree, but stays', () => {
  const got = card(wire([], [held1], 7), undefined);
  assert.ok(got !== null);
  assert.equal(got.agreeable, false);
  assert.equal(got.proposal, undefined);
  assert.deepEqual(got.items, [held1]);
});

test('the Agree button is enabled by the turn agree, by the rule as it is, not by the snapshot proposal', () => {
  const live = card(wire([], [held1], 7), 9);
  assert.ok(live !== null);
  assert.equal(live.agreeable, true);
  assert.equal(live.proposal, 9);
});

test('there is no card for a turn that held nothing', () => {
  assert.equal(card(wire([lamp]), undefined), null);
  assert.equal(card(wire([lamp]), 5), null);
  assert.equal(card(null, 5), null);
  assert.equal(card(undefined, undefined), null);
});
