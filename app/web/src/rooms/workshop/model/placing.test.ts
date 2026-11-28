import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BenchPiece, PieceKind } from '../../../api/types';
import { cardLinks, cardWidth, heldBox, mapPiece, placeOf, wholePt } from './placing.ts';

const kind = (format: PieceKind['format'], extra: Partial<PieceKind> = {}): PieceKind =>
  ({ name: format, family: 'stored', label: format, max_chars: 100, format, language: null, ...extra });
const piece = (id: number, placement: Partial<BenchPiece['placement']> = {}): BenchPiece =>
  ({ id, placement: { order: id, pin: null, box: null, ...placement } }) as BenchPiece;

test('a card is as wide as its kind wants', () => {
  assert.equal(cardWidth(kind('plain')), 300);
  assert.equal(cardWidth(kind('markdown')), 360);
  assert.equal(cardWidth(kind('code', { language: 'python' })), 440);
  assert.equal(cardWidth(kind('code', { language: 'build123d' })), 440);
  assert.equal(cardWidth(kind('image', { family: 'large' })), 440);
  assert.equal(cardWidth(undefined), 360);
});

test('links end at cards, drop self links, unknown kinds and repeats', () => {
  const cards = new Set([1, 2, 3]);
  const cardOf = (id: number) => (id === 7 ? 2 : id);
  const got = cardLinks([
    { from_id: 1, kind: 'part_of', to_id: 7 },
    { from_id: 1, kind: 'part_of', to_id: 2 },
    { from_id: 7, kind: 'depends_on', to_id: 2 },
    { from_id: 3, kind: 'mentions', to_id: 1 },
    { from_id: 3, kind: 'version_of', to_id: 9 },
    { from_id: 3, kind: 'version_of', to_id: 1 },
  ], cardOf, cards);
  assert.deepEqual(got, [{ from: 1, kind: 'part_of', to: 2 }, { from: 3, kind: 'version_of', to: 1 }]);
});

test('a move still on its way overrides the server, and leaving a field out keeps it', () => {
  const p = piece(1, { pin: { x: 5, y: 6 }, box: { w: 300, h: 200 } });
  assert.deepEqual(placeOf(p, undefined), { pin: { x: 5, y: 6 }, box: { w: 300, h: 200 } });
  assert.deepEqual(placeOf(p, { pin: { x: 9, y: 9 } }), { pin: { x: 9, y: 9 }, box: { w: 300, h: 200 } });
  assert.deepEqual(placeOf(p, { pin: null, box: null }), { pin: null, box: null });
  assert.deepEqual(placeOf(piece(2, { pin: undefined, box: undefined }), undefined), { pin: null, box: null });
});

test('a card waits to be measured unless it has a box', () => {
  assert.equal(mapPiece({ piece: piece(1), kind: kind('plain'), measured: undefined, pending: undefined }), null);
  assert.deepEqual(mapPiece({ piece: piece(1), kind: kind('plain'), measured: 181.2, pending: undefined }),
    { id: 1, order: 1, size: { w: 300, h: 182 }, pin: null });
  assert.deepEqual(mapPiece({ piece: piece(2, { box: { w: 500, h: 400 }, pin: { x: 1, y: 2 } }), kind: kind('plain'), measured: undefined, pending: undefined }),
    { id: 2, order: 2, size: { w: 500, h: 400 }, pin: { x: 1, y: 2 } });
});

test('a pin and a box go to the server whole, the box inside the bench bounds', () => {
  assert.deepEqual(wholePt({ x: 1.4, y: -2.6 }), { x: 1, y: -3 });
  assert.deepEqual(heldBox(10, 10), { w: 160, h: 80 });
  assert.deepEqual(heldBox(9000, 333.3), { w: 2400, h: 333 });
});
