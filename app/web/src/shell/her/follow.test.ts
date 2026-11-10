import assert from 'node:assert/strict';
import { test } from 'node:test';
import { follow, type PageState } from './follow.ts';

const idle: PageState = { focusedText: null, dragging: false, editing: false };

test('an idle page goes where she moved it', () => {
  assert.equal(follow('/', '/workshop/3', idle), 'go');
  assert.equal(follow('/', '/workshop/3', { ...idle, focusedText: '' }), 'go');
  assert.equal(follow('/', '/workshop/3', { ...idle, focusedText: '  \n' }), 'go');
});

test('a page already there stays, busy or not', () => {
  assert.equal(follow('/workshop/3', '/workshop/3', idle), 'stay');
  assert.equal(follow('/workshop/3', '/workshop/3', { ...idle, editing: true }), 'stay');
});

test('a page never moves out from under the person: typing, dragging or editing waits', () => {
  assert.equal(follow('/', '/workshop/3', { ...idle, focusedText: 'half a sente' }), 'wait');
  assert.equal(follow('/workshop/3', '/', { ...idle, dragging: true }), 'wait');
  assert.equal(follow('/workshop/3', '/workshop', { ...idle, editing: true }), 'wait');
});
