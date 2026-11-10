import assert from 'node:assert/strict';
import { test } from 'node:test';
import { markState, type Facts } from './ladder.ts';

const none: Facts = {
  unreachable: false, checking: false, hearing: null, speaking: false, liveSpeaking: false, asked: 0,
  remembering: 0, working: false, liveThinking: false, liveListening: false,
};

test('nothing going on is idle', () => {
  assert.equal(markState(none), 'idle');
});

test('a turn the served conversation says she is working on is thinking, as Live would say', () => {
  assert.equal(markState({ ...none, working: true }), 'thinking');
});

test('working does not outrank speaking, listening or being unreachable', () => {
  assert.equal(markState({ ...none, working: true, speaking: true }), 'speaking');
  assert.equal(markState({ ...none, working: true, hearing: 'listening' }), 'listening');
  assert.equal(markState({ ...none, working: true, unreachable: true }), 'unreachable');
});

test('the existing ladder is kept', () => {
  assert.equal(markState({ ...none, asked: 1 }), 'thinking');
  assert.equal(markState({ ...none, hearing: 'transcribing' }), 'thinking');
  assert.equal(markState({ ...none, liveListening: true }), 'listening');
  assert.equal(markState({ ...none, liveListening: true, liveThinking: true }), 'thinking');
  assert.equal(markState({ ...none, checking: true }), 'thinking');
});
