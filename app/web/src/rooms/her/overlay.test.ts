import assert from 'node:assert/strict';
import { test } from 'node:test';
import { awaiting, overlaid, type Line } from './overlay.ts';
import { stillOn } from './owed.ts';

const at = '2026-10-31T12:00:00Z';
const asked = (working?: boolean): Line => ({ key: 't1', author: 'person', text: 'is it raining', at, turn: 1, working });
const answer: Line = { key: 't2', author: 'ashley', text: 'No rain today.', at, turn: 2 };
const failed = (missed: Line['missed'] = 'unreachable'): Line => ({ ...asked(), key: 'l0', turn: undefined, missed });
const none = { failed: null, mine: null, hers: null };

test('a send that died is missed when no work for it is in flight', () => {
  const out = overlaid([asked(false)], { ...none, failed: failed() });
  assert.equal(out.length, 1);
  assert.equal(out[0]!.missed, 'unreachable');
});

test('a send that died while its turn is worked on elsewhere is not missed, and is not shown twice', () => {
  const out = overlaid([asked(true)], { ...none, failed: failed() });
  assert.equal(out.length, 1);
  assert.equal(out[0]!.missed, undefined);
});

test('a send she refused is missed even when a read-back still has the turn working', () => {
  const out = overlaid([asked(true)], { ...none, failed: failed('refused') });
  assert.equal(out[0]!.missed, 'refused');
});

test('a send that died before the turn was stored shows as missed', () => {
  const out = overlaid([], { ...none, failed: failed() });
  assert.deepEqual(out.map((l) => l.missed), ['unreachable']);
});

test('stillOn is whether the line owed an answer is being worked on', () => {
  assert.equal(stillOn([asked(true)]), true);
  assert.equal(stillOn([asked(false)]), false);
  assert.equal(stillOn([asked()]), false);
  assert.equal(stillOn([asked(true), answer]), false);
  assert.equal(stillOn([]), false);
});


test('a line she is working on shows her thinking though this page never saw her state', () => {
  assert.equal(awaiting([asked(true)], false, false), true);
  assert.equal(awaiting([asked(false)], false, false), false);
  assert.equal(awaiting([asked(false)], false, true), true);
  assert.equal(awaiting([{ ...asked(false), missed: 'failed' }], false, true), false);
});

const mine: Line = { key: 'l0', author: 'person', text: 'is it raining', at };

test('her thinking shows from the moment a message is sent, before the server has stored it', () => {
  const shown = overlaid([], { ...none, mine });
  assert.equal(awaiting(shown, true, true), true);
});

test('her thinking clears when her reply lands', () => {
  const shown = overlaid([asked(false)], { ...none, hers: { line: answer, held: false } });
  assert.equal(shown.at(-1)!.author, 'ashley');
  assert.equal(awaiting(shown, false, false), false);
  assert.equal(awaiting(shown, false, true), false);
});

test('her thinking clears when the send fails, though the page still believes she is thinking', () => {
  const shown = overlaid([], { ...none, failed: failed() });
  assert.equal(awaiting(shown, false, true), false);
});

test('her thinking clears when the turn is reported failed and the server no longer has it working', () => {
  const shown = overlaid([asked(false)], { ...none, failed: failed('failed') });
  assert.equal(awaiting(shown, false, true), false);
});

const started: Line = { key: 't9', author: 'household', text: '2 changes on the bench: #50 add image', at, turn: 9 };

test('her thinking shows for a turn the server started, from the live feed or the server read, with no send here', () => {
  assert.equal(awaiting([started], false, true), true);
  assert.equal(awaiting([{ ...started, working: true }], false, false), true);
  assert.equal(stillOn([{ ...started, working: true }]), true);
});

test('her thinking for a turn the server started clears when she answers it, when it fails and when the feed ends it', () => {
  assert.equal(awaiting([started, answer], false, false), false);
  assert.equal(awaiting([{ ...started, working: false }], false, false), false);
  assert.equal(awaiting([{ ...started, missed: 'failed' }], false, true), false);
  assert.equal(awaiting([started], false, false), false);
});
