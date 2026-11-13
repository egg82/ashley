import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { WireReceipts } from '../../api/types';
import { doneLine, hasMore, opens } from './receipts.ts';

const none = { headline: 'Sent an email', detail: null, why: null };
const some = { headline: 'Changed something in the house', detail: 'Changed something in the house (action: light.turn_on)', why: 'You asked for it.' };

test('the done line is the headlines, and nothing when nothing ran', () => {
  const both: WireReceipts = { ran: [some, none], held: [], proposal_id: null, choice_rows: [] };
  assert.equal(doneLine(both), 'Done: Changed something in the house, Sent an email');
  assert.equal(doneLine({ ran: [], held: [some], proposal_id: 4, choice_rows: [] }), null);
});

test('a note opens only when a receipt has a detail or a reason', () => {
  assert.equal(opens({ ran: [none], held: [], proposal_id: null, choice_rows: [] }), false);
  assert.equal(opens({ ran: [none, some], held: [], proposal_id: null, choice_rows: [] }), true);
  assert.equal(hasMore({ headline: 'x', detail: null, why: 'because' }), true);
  assert.equal(hasMore(none), false);
});
