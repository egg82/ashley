import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ConnectionKindInfo } from '../../../api/types';
import { bringBack, confirmsRemoval, costOf } from './remove.ts';

const kind = (over: Partial<ConnectionKindInfo>) => ({ connect: 'pasted', secret_noun: 'token', removed: 'Removed. She can’t reach the house now.', ...over }) as ConnectionKindInfo;

test('the name confirms it however it is cased or spaced, and nothing else does', () => {
  assert.equal(confirmsRemoval(' home assistant ', 'Home Assistant'), true);
  assert.equal(confirmsRemoval('Home', 'Home Assistant'), false);
  assert.equal(confirmsRemoval('', 'Home Assistant'), false);
});

test('how to bring it back follows how it was connected', () => {
  assert.equal(bringBack(kind({})), 'paste a new token');
  assert.equal(bringBack(kind({ connect: 'oauth' })), 'sign in again');
  assert.equal(bringBack(kind({ connect: 'bridge', secret_noun: '' })), 'paste a new login');
});

test('the kind’s own sentence is used without its leading word', () => {
  assert.equal(costOf(kind({})), 'She can’t reach the house now.');
  assert.equal(costOf(kind({ removed: 'She can’t reach it now.' })), 'She can’t reach it now.');
});
