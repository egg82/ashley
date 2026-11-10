import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { TaskRoutes } from '../../api/types.ts';
import { chosenAt, routeName, taskName, unoffered } from './routeChoice.ts';

const chat: TaskRoutes = {
  task: 'chat', household: true, chosen: null,
  routes: [{ provider: 'gemini', model: 'gemini-3.8-flash' }],
  options: [{ provider: 'gemini', model: 'gemini-3.8-flash' }, { provider: 'anthropic', model: 'claude-opus-5-5' }],
};

test('a task with no choice, a choice offered, and a choice no longer offered each read differently', () => {
  assert.equal(chosenAt(chat), -1);
  assert.equal(unoffered(chat), false);
  const opus = { ...chat, chosen: { provider: 'anthropic', model: 'claude-opus-5-5' } };
  assert.equal(chosenAt(opus), 1);
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
  assert.equal(taskName('action_judge'), 'Safety judge');
  assert.equal(taskName('errand'), 'errand');
  assert.equal(routeName({ provider: 'anthropic', model: 'claude-opus-5-5' }), 'claude-opus-5-5 (anthropic)');
});
