import assert from 'node:assert/strict';
import { test } from 'node:test';
import { NARROW, rowsOf, WIDE } from './rows.ts';

const SEED = [
  { kind: 'clock', size: 'small' },
  { kind: 'home', size: 'small' },
  { kind: 'controls', size: 'medium' },
  { kind: 'conversation', size: 'full' },
] as const;
const FILL = 'minmax(200px, 1fr)';

test('the seed is one row of glance and controls on a wide screen, and the conversation fills the rest', () => {
  assert.equal(rowsOf(SEED, WIDE), `auto ${FILL}`);
});

test('on a narrow screen the controls take their own row above the conversation', () => {
  assert.equal(rowsOf(SEED, NARROW), `auto auto ${FILL}`);
});

test('the row that fills is the one holding the conversation, wherever it is placed', () => {
  const placed = [SEED[3], SEED[2], SEED[0]] as const;
  assert.equal(rowsOf(placed, WIDE), `${FILL} auto`);
});

test('a conversation beside other pieces fills their row', () => {
  assert.equal(rowsOf([{ kind: 'controls', size: 'large' }, { kind: 'conversation', size: 'small' }], WIDE), FILL);
});

test('a piece that does not fit the row it is in starts the next one', () => {
  const rows = rowsOf([{ kind: 'home', size: 'large' }, { kind: 'clock', size: 'medium' }, { kind: 'conversation', size: 'full' }], WIDE);
  assert.equal(rows, `auto auto ${FILL}`);
});
