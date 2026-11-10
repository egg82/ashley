// A bench's order on this screen. Pure. Each size class's share of the row (`WorkshopKinds.sizes`: small a quarter,
// medium a half, large three quarters, full the row) is the grid's, in `workshop.css`.
import type { BenchPiece, PieceSize } from '../../../api/types';

const SHORT: Record<PieceSize, string> = { small: 'S', medium: 'M', large: 'L', full: 'F' };

/** The one letter a size's control shows. */
export function shortOf(size: PieceSize): string {
  return SHORT[size];
}

/** The pieces in their order. */
export function ordered(pieces: readonly BenchPiece[]): BenchPiece[] {
  return [...pieces].sort((a, b) => a.placement.order - b.placement.order);
}

/** `ids` with `id` taken out and put back at index `to` (clamped to the ends). */
export function movedTo(ids: readonly number[], id: number, to: number): number[] {
  const rest = ids.filter((i) => i !== id);
  if (rest.length === ids.length) return [...ids];
  const at = Math.max(0, Math.min(rest.length, to));
  return [...rest.slice(0, at), id, ...rest.slice(at)];
}

/** The pieces in the order `ids` gives, any piece it leaves out at the end in its own order. */
export function inOrder(pieces: readonly BenchPiece[], ids: readonly number[] | null): BenchPiece[] {
  const sorted = ordered(pieces);
  if (!ids) return sorted;
  const at = new Map(ids.map((id, i) => [id, i]));
  return sorted
    .map((p, i) => ({ p, key: at.get(p.id) ?? ids.length + i }))
    .sort((a, b) => a.key - b.key)
    .map(({ p }) => p);
}

/** Where piece `id` goes in the whole order `all` when it is let go at index `to` of the order `visible` (the pieces the
 *  screen shows, which leave out some of `all`): in front of the shown piece that follows it, else last. Indexes count
 *  with `id` taken out, as `movedTo` does. */
export function fullIndex(all: readonly number[], visible: readonly number[], id: number, to: number): number {
  const rest = all.filter((i) => i !== id);
  const shown = visible.filter((i) => i !== id);
  const before = shown[Math.max(0, to)];
  return before === undefined ? rest.length : rest.indexOf(before);
}
