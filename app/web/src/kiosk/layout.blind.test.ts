// Contract 17: `validLayout` answers null for anything but a laid-out, well-formed layout, and the layout itself for one.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { validLayout } from './layout.ts';

interface Piece {
  id: number;
  kind: string;
  order: number;
  size: string;
}

const CLOCK: Piece = { id: 1, kind: 'clock', order: 0, size: 'small' };
const HOME: Piece = { id: 2, kind: 'home', order: 1, size: 'small' };
const CONTROLS: Piece = { id: 3, kind: 'controls', order: 2, size: 'medium' };
const CONVERSATION: Piece = { id: 4, kind: 'conversation', order: 3, size: 'full' };
const SEED = [CLOCK, HOME, CONTROLS, CONVERSATION];

function layout(pieces: unknown, extra: Record<string, unknown> = {}): unknown {
  return { laid_out: true, seq: 5, placed: pieces, ...extra };
}

function piecesOf(got: unknown): Piece[] {
  assert.ok(typeof got === 'object' && got !== null, 'a layout is an object');
  const pieces: unknown = (got as { placed?: unknown }).placed;
  assert.ok(Array.isArray(pieces), 'a layout holds its pieces');
  return pieces as Piece[];
}

function ids(got: unknown): number[] {
  return piecesOf(got)
    .map((p) => p.id)
    .sort((a, b) => a - b);
}

test('a well-formed laid-out layout is returned with every piece', () => {
  const got = validLayout(layout(SEED));
  assert.notEqual(got, null);
  assert.deepEqual(ids(got), [1, 2, 3, 4]);
  for (const want of SEED) {
    assert.deepEqual(
      piecesOf(got).find((p) => p.id === want.id),
      want,
    );
  }
});

test('a layout of the conversation alone, or of any sizes, is well formed', () => {
  assert.deepEqual(ids(validLayout(layout([{ ...CONVERSATION, order: 0 }]))), [4]);
  for (const size of ['small', 'medium', 'large', 'full']) {
    assert.notEqual(validLayout(layout(SEED.map((p) => ({ ...p, size })))), null, size);
  }
});

test('the pieces may arrive in any order so long as their orders are 0 to n-1', () => {
  const shuffled = [CONVERSATION, CLOCK, CONTROLS, HOME];
  assert.deepEqual(ids(validLayout(layout(shuffled))), [1, 2, 3, 4]);
});

test('a layout that is not laid out is null, whatever else it says', () => {
  assert.equal(validLayout({ laid_out: false, seq: 0, placed: SEED }), null);
  assert.equal(validLayout({ laid_out: false, seq: 0, placed: [] }), null);
  assert.equal(validLayout({ seq: 5, placed: SEED }), null);
  assert.equal(validLayout({ laid_out: 'true', seq: 5, placed: SEED }), null);
  assert.equal(validLayout({ laid_out: 1, seq: 5, placed: SEED }), null);
});

test('a gap, a duplicate or an offset in the orders is null', () => {
  assert.equal(validLayout(layout([CLOCK, HOME, { ...CONTROLS, order: 3 }, { ...CONVERSATION, order: 4 }])), null);
  assert.equal(validLayout(layout([CLOCK, { ...HOME, order: 0 }, CONTROLS, { ...CONVERSATION, order: 2 }])), null);
  assert.equal(validLayout(layout([CLOCK, HOME, CONTROLS, { ...CONVERSATION, order: 2 }])), null);
  assert.equal(validLayout(layout(SEED.map((p) => ({ ...p, order: p.order + 1 })))), null);
  assert.equal(validLayout(layout(SEED.map((p) => ({ ...p, order: p.order - 1 })))), null);
  assert.equal(validLayout(layout([CLOCK, HOME, CONTROLS, { ...CONVERSATION, order: 1.5 }])), null);
  assert.equal(validLayout(layout([CLOCK, HOME, CONTROLS, { ...CONVERSATION, order: '3' }])), null);
});

test('a duplicate id is null', () => {
  assert.equal(validLayout(layout([CLOCK, HOME, { ...CONTROLS, id: 1 }, CONVERSATION])), null);
  assert.equal(validLayout(layout([CLOCK, HOME, CONTROLS, { ...CONVERSATION, id: 3 }])), null);
});

test('a kind outside the four is null', () => {
  for (const kind of ['note', 'site', 'document', 'Clock', '', 'conversations']) {
    assert.equal(validLayout(layout([CLOCK, HOME, { ...CONTROLS, kind }, CONVERSATION])), null, kind);
  }
});

test('a size outside the size classes is null', () => {
  for (const size of ['huge', 'Small', '', 'half', 3]) {
    assert.equal(validLayout(layout([{ ...CLOCK, size }, HOME, CONTROLS, CONVERSATION])), null, String(size));
  }
});

test('a layout with no conversation piece is null', () => {
  assert.equal(validLayout(layout([CLOCK, HOME, CONTROLS])), null);
  assert.equal(validLayout(layout([])), null);
  assert.equal(validLayout(layout([CLOCK])), null);
});

test('a piece missing a field, or that is not an object, is null', () => {
  for (const field of ['id', 'kind', 'order', 'size'] as const) {
    const { [field]: _gone, ...rest } = CLOCK;
    assert.equal(validLayout(layout([rest, HOME, CONTROLS, CONVERSATION])), null, field);
  }
  assert.equal(validLayout(layout([null, HOME, CONTROLS, CONVERSATION])), null);
  assert.equal(validLayout(layout(['clock', HOME, CONTROLS, CONVERSATION])), null);
});

test('anything that is not an object, or whose pieces are not a list, is null', () => {
  for (const raw of [null, undefined, 5, 'layout', true, [], SEED, () => SEED]) {
    assert.equal(validLayout(raw), null, String(raw));
  }
  for (const pieces of [undefined, null, 'x', 4, { 0: CLOCK }]) {
    assert.equal(validLayout(layout(pieces)), null, String(pieces));
  }
});
