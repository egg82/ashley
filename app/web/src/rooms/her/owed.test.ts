import assert from 'node:assert/strict';
import { test } from 'node:test';
import { answered, owedAt } from './owed.ts';

const asked = { author: 'person', text: 'is it raining' } as const;
const held = { author: 'ashley', text: 'Let me check.', follows: true } as const;
const answer = { author: 'ashley', text: 'No rain today.' } as const;

test('a person line last is owed', () => {
  assert.equal(owedAt([answer, asked]), 1);
});

test('her held lines after it still owe it', () => {
  assert.equal(owedAt([asked, held]), 0);
  assert.equal(owedAt([asked, held, held]), 0);
});

test('her answer after a held line ends what is owed', () => {
  assert.equal(owedAt([asked, held, answer]), -1);
  assert.equal(owedAt([asked, answer]), -1);
  assert.equal(owedAt([]), -1);
  assert.equal(owedAt([held]), -1);
});

test('answered is her answer to that text, held lines between', () => {
  assert.equal(answered([asked, held, answer], asked.text), true);
  assert.equal(answered([asked, answer], asked.text), true);
  assert.equal(answered([asked, held], asked.text), false);
  assert.equal(answered([asked, held, answer], 'something else'), false);
  assert.equal(answered([asked], asked.text), false);
});
