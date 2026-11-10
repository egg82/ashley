import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BenchPiece } from '../../../api/types';
import { fullIndex } from './layout.ts';
import { groupDerived } from './derived.ts';

const piece = (id: number, recording: number | null = null): BenchPiece =>
  ({ id, kind: 'note', title: `p${id}`, body: '', piece_version: 1, placement: { order: id, size: 'medium' }, changed_by: id, changed_at: '2026-10-29T12:00:00Z', changed_author: 'person', changed_person_id: 1, last_run: null, automation: null, video: null,
    reader: { url: '', title: `t${id}`, paragraphs: ['a'], recording: recording === null ? null : { piece_id: recording, starts: [0] } } as BenchPiece['reader'], pointer: null, file: null, site: null, recipe: null });

test('a transcript is shown with the recording it names (a piece derived from another), and takes no card of its own', () => {
  const grouped = groupDerived([piece(1), piece(2, 1), piece(3)]);
  assert.deepEqual(grouped.cards.map((p) => p.id), [1, 3]);
  assert.deepEqual(grouped.derived.get(1)?.map((p) => p.id), [2]);
});

test('a transcript naming no recording on the bench, itself, or another derived piece stays a card', () => {
  const none = groupDerived([piece(2, 9), piece(3, 3), piece(4, 5), piece(5, 4)]);
  assert.deepEqual(none.cards.map((p) => p.id), [2, 3, 4, 5]);
  assert.equal(none.derived.size, 0);
});

test('a reader with no recording is not grouped, whatever its title says', () => {
  const plain = piece(2);
  plain.title = 'Transcript of p1';
  assert.deepEqual(groupDerived([piece(1), plain]).cards.map((p) => p.id), [1, 2]);
});

test('two transcripts of one recording are both shown with it, in order', () => {
  assert.deepEqual(groupDerived([piece(1), piece(2, 1), piece(3, 1)]).derived.get(1)?.map((p) => p.id), [2, 3]);
});

test('a drop among the shown pieces lands in the whole order in front of the shown piece after it', () => {
  const all = [1, 2, 3, 4, 5];
  const visible = [1, 3, 4, 5];
  assert.equal(fullIndex(all, visible, 1, 1), 2);
  assert.equal(fullIndex(all, visible, 1, 3), 4);
  assert.equal(fullIndex(all, visible, 5, 0), 0);
  assert.equal(fullIndex(all, visible, 3, 99), 4);
});
