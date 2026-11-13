import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TaskRoutes } from '../../api/types.ts';
import { chainOf, choicesOf, chosenAt, routeName, selectedOf, taskName, unoffered } from './routeChoice.ts';

const chat: TaskRoutes = {
  task: 'chat', household: true, chosen: null,
  routes: [{ provider: 'gemini', model: 'gemini-3.8-flash' }, { provider: 'anthropic', model: 'claude-sonnet-5-5' }],
  options: [{ provider: 'gemini', model: 'gemini-3.8-flash' }, { provider: 'anthropic', model: 'claude-sonnet-5-5' }, { provider: 'anthropic', model: 'claude-opus-5-5' }],
};

test('a task with no choice, a choice offered, and a choice no longer offered each read differently', () => {
  assert.equal(chosenAt(chat), -1);
  assert.equal(unoffered(chat), false);
  const opus = { ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-5-5' } };
  assert.equal(chosenAt(opus), 2);
  assert.equal(unoffered(opus), false);
  const gone = { ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-4' } };
  assert.equal(chosenAt(gone), -1);
  assert.equal(unoffered(gone), true);
});

test('a choice matches on provider and model together', () => {
  const sameModel = { ...chat, chosen: { provider: 'openai', model: 'claude-opus-5-5' } };
  assert.equal(chosenAt(sameModel), -1);
});

test('names read as a person would and fall back to the id', () => {
  assert.equal(taskName('action_judge'), 'Action judge');
  assert.equal(taskName('new_thing'), 'New thing');
  assert.equal(routeName({ provider: 'anthropic', model: 'claude-opus-5-5' }), 'claude-opus-5-5 (anthropic)');
});

test('a call tries the household choice first and then the deployment routes, once each', () => {
  assert.deepEqual(chainOf(chat).map((r) => r.model), ['gemini-3.8-flash', 'claude-sonnet-5-5']);
  const opus = { ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-5-5' } };
  assert.deepEqual(chainOf(opus).map((r) => r.model), ['claude-opus-5-5', 'gemini-3.8-flash', 'claude-sonnet-5-5']);
  const dup = { ...chat, chosen: { provider: 'anthropic', model: 'claude-sonnet-5-5' } };
  assert.deepEqual(chainOf(dup).map((r) => r.model), ['claude-sonnet-5-5', 'gemini-3.8-flash']);
  const gone = { ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-4' } };
  assert.deepEqual(chainOf(gone).map((r) => r.model), ['gemini-3.8-flash', 'claude-sonnet-5-5']);
});

test('the select offers her default once, then the other models by option index', () => {
  assert.deepEqual(choicesOf(chat), [
    { value: '-1', label: 'gemini-3.8-flash (her default)' },
    { value: '1', label: 'claude-sonnet-5-5 (anthropic)' },
    { value: '2', label: 'claude-opus-5-5 (anthropic)' },
  ]);
});

test('the select shows her default for no choice, for her default chosen, and for a choice no longer offered', () => {
  assert.equal(selectedOf(chat), '-1');
  assert.equal(selectedOf({ ...chat, chosen: { provider: 'gemini', model: 'gemini-3.8-flash' } }), '-1');
  assert.equal(selectedOf({ ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-5-5' } }), '2');
  assert.equal(selectedOf({ ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-4' } }), '-1');
});
