import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WireReceipts } from '../../api/types';
import { foldLine, foldOf } from './fold.ts';

const ran = { headline: 'Sent an email', detail: null, why: null };
const done: WireReceipts = { ran: [ran], held: [], proposal_id: null, choice_rows: [] };
const held: WireReceipts = { ran: [], held: [{ headline: 'Unlock the door', detail: null, why: null }], proposal_id: 4, choice_rows: [] };

test('pictures and the done note fold into one line, closed', () => {
  const folded = foldOf(done, [{}, {}]);
  assert.deepEqual(folded, { pictures: 2, note: true });
  assert.equal(foldLine(folded!), '2 pictures · details');
  assert.equal(foldLine({ pictures: 1, note: false }), '1 picture');
  assert.equal(foldLine({ pictures: 0, note: true }), 'details');
});

test('a held card waits on a decision, so it adds nothing to the fold', () => {
  assert.equal(foldOf(held, undefined), null);
  assert.deepEqual(foldOf(held, [{}]), { pictures: 1, note: false });
});

test('a message with no pictures and nothing that ran has no fold', () => {
  assert.equal(foldOf(null, []), null);
  assert.equal(foldOf(undefined, undefined), null);
});
