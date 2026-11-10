import assert from 'node:assert/strict';
import { test } from 'node:test';
import { answered, owedAt } from './owed.ts';

const ask = (text: string) => ({ author: 'person', text }) as const;
const held = (text = 'Let me check.') => ({ author: 'ashley', text, follows: true }) as const;
const said = (text: string) => ({ author: 'ashley', text }) as const;
const unmarked = (text: string) => ({ author: 'ashley', text, follows: false }) as const;

test('owedAt is the index of the person line still owed an answer, or -1', () => {
  assert.equal(owedAt([]), -1);
  assert.equal(owedAt([ask('a')]), 0);
  assert.equal(owedAt([said('x'), ask('a')]), 1);
});

test('a held line after the person line leaves it owed, however many', () => {
  assert.equal(owedAt([ask('a'), held()]), 0);
  assert.equal(owedAt([ask('a'), held('one'), held('two'), held('three')]), 0);
  assert.equal(owedAt([said('old'), ask('a'), held()]), 1);
});

test('an unmarked line of hers after the person line ends what is owed, whether follows is absent or false', () => {
  assert.equal(owedAt([ask('a'), said('done')]), -1);
  assert.equal(owedAt([ask('a'), unmarked('done')]), -1);
  assert.equal(owedAt([ask('a'), held(), said('done')]), -1);
  assert.equal(owedAt([ask('a'), held(), unmarked('done')]), -1);
});

test('only the trailing run counts: a held line then a newer person line owes the newer one', () => {
  assert.equal(owedAt([ask('a'), held(), ask('b')]), 2);
  assert.equal(owedAt([ask('a'), held(), said('done'), ask('b'), held()]), 3);
});

test('a held line with no person line before it owes nothing', () => {
  assert.equal(owedAt([held()]), -1);
  assert.equal(owedAt([said('hi'), held()]), -1);
});

test('an answer to one question does not hide a later one', () => {
  assert.equal(owedAt([ask('a'), said('x'), ask('b')]), 2);
});

test('answered is true only when her unmarked line follows that exact text, held lines between', () => {
  assert.equal(answered([ask('a'), said('x')], 'a'), true);
  assert.equal(answered([ask('a'), held(), said('x')], 'a'), true);
  assert.equal(answered([ask('a'), held(), held(), unmarked('x')], 'a'), true);
});

test('answered is false while only held lines follow, or nothing does', () => {
  assert.equal(answered([ask('a'), held()], 'a'), false);
  assert.equal(answered([ask('a'), held(), held()], 'a'), false);
  assert.equal(answered([ask('a')], 'a'), false);
  assert.equal(answered([], 'a'), false);
});

test('answered is false for text that is not the owed person line', () => {
  assert.equal(answered([ask('a'), said('x')], 'b'), false);
  assert.equal(answered([ask('a'), said('x'), ask('b')], 'a'), false);
  assert.equal(answered([ask('a'), said('x'), ask('b'), held()], 'b'), false);
});

test('answered is true for the newest question once answered even after an older one was', () => {
  assert.equal(answered([ask('a'), said('x'), ask('b'), held(), said('y')], 'b'), true);
});

test('answered names the person line her answer is to, not an earlier one nor her own words', () => {
  assert.equal(answered([ask('a'), said('x'), ask('b'), said('y')], 'a'), false);
  assert.equal(answered([ask('a'), said('x')], 'x'), false);
});
