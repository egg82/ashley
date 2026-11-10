import assert from 'node:assert/strict';
import { test } from 'node:test';
import { sharedFor, whoOf } from './who.ts';

test('a kept resource reads as just me and a shared one as the household', () => {
  assert.equal(whoOf(false), 'me');
  assert.equal(whoOf(true), 'household');
});

test('choosing the other side sends that side, and choosing the current one sends nothing', () => {
  assert.equal(sharedFor(false, 'household'), true);
  assert.equal(sharedFor(true, 'me'), false);
  assert.equal(sharedFor(false, 'me'), null);
  assert.equal(sharedFor(true, 'household'), null);
});
