import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PASTE_MIN } from '../limit.ts';
import { classifyDrop, FILES_WORDS, textOf, wordsFor } from './drops.ts';

test('files win over any text that came with them', () => {
  assert.equal(classifyDrop('photo.jpg', 1), 'files');
});

test('a short line or a link is sent as a line, a long paste becomes the chip, nothing is nothing', () => {
  assert.equal(classifyDrop('https://example.com/a', 0), 'line');
  assert.equal(classifyDrop('x'.repeat(PASTE_MIN + 1), 0), 'chip');
  assert.equal(classifyDrop('   ', 0), 'none');
});

test('the text of a drop is its plain text, else the first address of its link list', () => {
  const data = (m: Record<string, string>) => ({ getData: (t: string) => m[t] ?? '' });
  assert.equal(textOf(data({ 'text/plain': 'hi' })), 'hi');
  assert.equal(textOf(data({ 'text/uri-list': '# note\nhttps://a.example/\nhttps://b.example/' })), 'https://a.example/');
  assert.equal(textOf(data({})), '');
});

test('files go with what was typed, or a line of their own', () => {
  assert.equal(wordsFor('  what is this  '), 'what is this');
  assert.equal(wordsFor(' '), FILES_WORDS);
});
