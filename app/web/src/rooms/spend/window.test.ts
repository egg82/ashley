import assert from 'node:assert/strict';
import { test } from 'node:test';
import { response } from './fixtures.ts';
import { startsAt, whenOf, winOf } from './window.ts';

test('the address names a window, and anything else is the month', () => {
  assert.equal(winOf('today'), 'today');
  assert.equal(winOf('week'), 'week');
  assert.equal(winOf(undefined), 'month');
  assert.equal(winOf('year'), 'month');
});

test('a window reads in a sentence and says when it starts', () => {
  assert.equal(whenOf('week'), 'this week');
  assert.equal(startsAt(response([]), 'week'), '2026-11-07T00:00:00Z');
});
