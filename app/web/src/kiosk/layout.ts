// The kiosk's layout as the page trusts it: the server's `KioskLayout` when it is whole, else nothing, and the page
// shows its fixed arrangement. A half-drawn layout reads as working, so one defect anywhere rejects all of it.
import type { KioskLayout, PieceSize } from '../api/types';

export type Layout = KioskLayout;

export const SIZES: readonly PieceSize[] = ['small', 'medium', 'large', 'full'];
/** The pieces this page can draw. */
export const KINDS: readonly string[] = ['clock', 'home', 'conversation', 'controls'];

function record(raw: unknown): Record<string, unknown> | null {
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
}

function whole(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

/**
 * `raw` as a Layout, its pieces in order, or null when it is not one: not laid out, an id used twice, orders that are not
 * exactly 0 to n-1, a size or kind this page does not know, no conversation piece, or not an object at all.
 */
export function validLayout(raw: unknown): Layout | null {
  const top = record(raw);
  if (!top || top.laid_out !== true || !whole(top.seq) || !Array.isArray(top.placed)) return null;
  const pieces: Layout['placed'] = [];
  for (const item of top.placed as unknown[]) {
    const piece = record(item);
    if (!piece || !whole(piece.id) || !whole(piece.order) || typeof piece.kind !== 'string' || typeof piece.size !== 'string') return null;
    if (!KINDS.includes(piece.kind) || !(SIZES as readonly string[]).includes(piece.size)) return null;
    pieces.push({ id: piece.id, kind: piece.kind, order: piece.order, size: piece.size as PieceSize });
  }
  pieces.sort((a, b) => a.order - b.order);
  if (new Set(pieces.map((p) => p.id)).size !== pieces.length) return null;
  if (!pieces.every((p, i) => p.order === i)) return null;
  if (!pieces.some((p) => p.kind === 'conversation')) return null;
  return { laid_out: true, seq: top.seq, placed: pieces };
}
