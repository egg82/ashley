import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BenchPiece } from '../../../api/types';
import { inOrder, movedTo, ordered } from './layout.ts';

const piece = (id: number, order: number): BenchPiece =>
  ({ id, kind: 'note', title: `p${id}`, body: '', piece_version: 1, placement: { order, size: 'medium' }, changed_by: id, changed_at: '2026-10-29T12:00:00Z', changed_author: 'person', changed_person_id: 1, last_run: null, automation: null, video: null, reader: null, pointer: null, file: null, site: null, recipe: null });

test('pieces in their order', () => {
  assert.deepEqual(ordered([piece(3, 2), piece(1, 0), piece(2, 1)]).map((p) => p.id), [1, 2, 3]);
});

test('a piece moved to an index, clamped to the ends', () => {
  assert.deepEqual(movedTo([1, 2, 3, 4], 1, 2), [2, 3, 1, 4]);
  assert.deepEqual(movedTo([1, 2, 3, 4], 4, 0), [4, 1, 2, 3]);
  assert.deepEqual(movedTo([1, 2, 3], 2, 99), [1, 3, 2]);
  assert.deepEqual(movedTo([1, 2, 3], 2, -5), [2, 1, 3]);
});

test('moving a piece not in the order changes nothing', () => {
  assert.deepEqual(movedTo([1, 2], 7, 0), [1, 2]);
});

test('a preview order wins, and pieces it leaves out follow in their own order', () => {
  const pieces = [piece(1, 0), piece(2, 1), piece(3, 2)];
  assert.deepEqual(inOrder(pieces, null).map((p) => p.id), [1, 2, 3]);
  assert.deepEqual(inOrder(pieces, [3, 1]).map((p) => p.id), [3, 1, 2]);
});
