import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { cut } from './passage.ts';

test('a passage is cut out of its paragraph', () => {
  assert.deepEqual(cut('first line', 6, 10), { before: 'first ', hit: 'line', after: '' });
  assert.deepEqual(cut('first line', 0, 5), { before: '', hit: 'first', after: ' line' });
});

test('characters are counted in code points, so an emoji before the passage is one character', () => {
  assert.deepEqual(cut('😀😀 ab', 3, 5), { before: '😀😀 ', hit: 'ab', after: '' });
  assert.notDeepEqual(cut('😀😀 ab', 3, 5), { before: '😀😀', hit: ' a', after: 'b' });
});

test('every passage the server located cuts back to its quote, accents and emoji before it included', () => {
  const shared = JSON.parse(readFileSync(new URL('../../../../../tests/reader_passages.json', import.meta.url), 'utf8'));
  const lines: string[] = shared.text.split('\n');
  assert.ok(shared.cases.length >= 4);
  for (const c of shared.cases) assert.equal(cut(lines[c.paragraph]!, c.start, c.end).hit, c.quote);
});
