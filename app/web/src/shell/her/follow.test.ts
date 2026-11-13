import assert from 'node:assert/strict';
import { test } from 'node:test';
import { follow, replaces, workingAway, type PageState } from './follow.ts';

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

test('her change to a bench the page is not on shows her working there', () => {
  assert.equal(workingAway(null, 3, 'her'), true);
  assert.equal(workingAway(2, 3, 'her'), true);
});

test('her change to the bench the page is on shows nothing, it is the bench\'s own marks to say', () => {
  assert.equal(workingAway(3, 3, 'her'), false);
});

test('the person\'s own change, on another screen or none, never shows her working', () => {
  assert.equal(workingAway(null, 3, 'person'), false);
  assert.equal(workingAway(null, 3, null), false);
});

test('a newer working replaces the one waiting, but never an offer to follow a move', () => {
  assert.equal(replaces(null, 'working'), true);
  assert.equal(replaces('working', 'working'), true);
  assert.equal(replaces('working', 'moved'), true);
  assert.equal(replaces('moved', 'moved'), true);
  assert.equal(replaces('moved', 'working'), false);
});
