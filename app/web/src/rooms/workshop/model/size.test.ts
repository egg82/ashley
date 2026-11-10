import assert from 'node:assert/strict';
import { test } from 'node:test';
import { bytesText, typeText } from './size.ts';

test('a size is bytes, then KB, MB, GB, one decimal below ten', () => {
  assert.equal(bytesText(0), '0 B');
  assert.equal(bytesText(999), '999 B');
  assert.equal(bytesText(1000), '1.0 KB');
  assert.equal(bytesText(1536), '1.5 KB');
  assert.equal(bytesText(25_000_000), '25 MB');
  assert.equal(bytesText(26_214_400), '26 MB');
  assert.equal(bytesText(3_000_000_000), '3.0 GB');
});

test('a type is the subtype in capitals, plain text as TEXT', () => {
  assert.equal(typeText('application/pdf'), 'PDF');
  assert.equal(typeText('image/png'), 'PNG');
  assert.equal(typeText('text/plain'), 'TEXT');
  assert.equal(typeText('text/csv'), 'CSV');
});
