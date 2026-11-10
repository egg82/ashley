import assert from 'node:assert/strict';
import { test } from 'node:test';
import { polled, POLL_MS } from './polling.ts';

test('the glance is read on its timer with the feed up, since nothing announces who is home', () => {
  assert.equal(polled('glance', true), true);
  assert.equal(polled('glance', false), true);
});

test('the conversation is read on its timer only while the feed is down', () => {
  assert.equal(polled('conversation', true), false);
  assert.equal(polled('conversation', false), true);
});

test('both parts have an interval', () => {
  assert.ok(POLL_MS.glance > 0 && POLL_MS.conversation > 0);
});
