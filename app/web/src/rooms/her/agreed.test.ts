import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ChatConversationTurn, WireAgreed } from '../../api/types';
import { storedLine } from './overlay.ts';
import { copy } from './receiptCopy.ts';
import { agreedLines } from './receipts.ts';

const agreed: WireAgreed = {
  interrupted: false,
  carried: [
    { summary: 'Turn on the hall lamp', status: 'ran' },
    { summary: 'Open the garage door', status: 'failed' },
    { summary: 'Label a message: Bills', status: 'ran' },
    { summary: 'Move a message', status: 'not_run' },
  ],
};

test('beside an Agree, each outcome some call had is one line of its summaries, in a fixed order', () => {
  assert.deepEqual(agreedLines(agreed), [
    `${copy.done}: Turn on the hall lamp, Label a message: Bills`,
    `${copy.failed}: Open the garage door`,
    `${copy.notRun}: Move a message`,
  ]);
  assert.deepEqual(agreedLines({ interrupted: false, carried: [{ summary: 'Open the garage door', status: 'failed' }] }),
    [`${copy.failed}: Open the garage door`]);
});

test('an interrupted run is its own line and names no call', () => {
  assert.deepEqual(agreedLines({ interrupted: true, carried: [] }), [copy.interrupted]);
});

test("the person's agreeing turn carries its outcome to the line it shows, and every other turn carries none", () => {
  const turn: ChatConversationTurn = {
    id: 7, author: 'person', text: 'Agreed.', at: '2026-11-09T12:00:00Z', follows: false, continued_on: null,
    attachment: null, runs: [], looks: [], working: false, agree: null, voiced: false, agreed,
  };
  assert.deepEqual(storedLine(turn).agreed, agreed);
  assert.equal(storedLine({ ...turn, agreed: null }).agreed, undefined);
  assert.equal(storedLine({ ...turn, agreed: undefined }).agreed, undefined);
});
