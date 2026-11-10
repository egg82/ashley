import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BACKOFF_MS, counted, decide, QUIET_MS, type Facts } from './update.ts';

const quiet: Facts = { booted: 'aaa', served: 'bbb', tries: {}, now: 1e9, idleMs: QUIET_MS + 1, interacted: true, held: false };

test('a new build on a quiet page reloads', () => {
  assert.equal(decide(quiet), 'reload');
});

test('the same build, or no answer yet, is current', () => {
  assert.equal(decide({ ...quiet, served: 'aaa' }), 'current');
  assert.equal(decide({ ...quiet, served: null }), 'current');
  assert.equal(decide({ ...quiet, booted: null }), 'current');
});

test('dev never reloads, on either side', () => {
  assert.equal(decide({ ...quiet, booted: 'dev' }), 'current');
  assert.equal(decide({ ...quiet, served: 'dev' }), 'current');
});

test('held, or touched a moment ago, waits; never touched reloads at once', () => {
  assert.equal(decide({ ...quiet, held: true }), 'wait');
  assert.equal(decide({ ...quiet, idleMs: QUIET_MS - 1 }), 'wait');
  assert.equal(decide({ ...quiet, idleMs: 0, interacted: false }), 'reload');
});

test('a build reloaded for and still served old backs off, then tries again, then gives up', () => {
  let tries = counted({}, 'bbb', quiet.now);
  assert.equal(decide({ ...quiet, tries, now: quiet.now + BACKOFF_MS[0]! - 1 }), 'backoff');
  assert.equal(decide({ ...quiet, tries, now: quiet.now + BACKOFF_MS[0]! }), 'reload');
  tries = counted(tries, 'bbb', quiet.now);
  assert.equal(decide({ ...quiet, tries, now: quiet.now + BACKOFF_MS[1]! - 1 }), 'backoff');
  tries = counted(tries, 'bbb', quiet.now);
  assert.equal(decide({ ...quiet, tries, now: quiet.now + 1e12 }), 'gave-up');
});

test('tries belong to the build they were made for', () => {
  const tries = counted({}, 'bbb', quiet.now);
  assert.equal(decide({ ...quiet, served: 'ccc', tries }), 'reload');
});
