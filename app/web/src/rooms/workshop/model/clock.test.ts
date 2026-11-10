import assert from 'node:assert/strict';
import { test } from 'node:test';
import { clockText, cueText } from './clock.ts';

test('a time is minutes and seconds, and hours from an hour on', () => {
  assert.deepEqual([0, 5.9, 65, 599, 3599, 3600, 3723, -4].map(clockText), ['0:00', '0:05', '1:05', '9:59', '59:59', '1:00:00', '1:02:03', '0:00']);
});

test('a cue is said in words, a seek with where it went', () => {
  assert.equal(cueText({ action: 'seek', seconds: 125 }), 'Ashley moved to 2:05');
  assert.equal(cueText({ action: 'play', seconds: null }), 'Ashley pressed play');
  assert.equal(cueText({ action: 'pause', seconds: null }), 'Ashley paused it');
});
