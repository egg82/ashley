// The row heights of a laid-out screen's grid. Pieces flow left to right on four columns, wrapping when one does not fit;
// the row holding the conversation takes the height the others leave, so its messages scroll inside it and its composer
// stays at the foot of the screen. Every other row is as tall as its tallest piece.
import type { PieceSize } from '../api/types';

type Spans = Record<PieceSize, number>;

/** Columns a size takes of four on a wide screen, and of four on a narrow one (small a half, the rest the row). */
export const WIDE: Spans = { small: 1, medium: 2, large: 3, full: 4 };
export const NARROW: Spans = { small: 2, medium: 4, large: 4, full: 4 };

/** The `grid-template-rows` for pieces in order, given as (kind, size), laid out with `spans`. */
export function rowsOf(pieces: readonly { kind: string; size: PieceSize }[], spans: Spans): string {
  const rows: boolean[] = [];
  let used = 0;
  for (const p of pieces) {
    const span = spans[p.size];
    if (rows.length === 0 || used + span > 4) {
      rows.push(false);
      used = 0;
    }
    used += span;
    if (p.kind === 'conversation') rows[rows.length - 1] = true;
  }
  return rows.map((fills) => (fills ? 'minmax(200px, 1fr)' : 'auto')).join(' ');
}
