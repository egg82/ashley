// What the bench canvas keeps beyond one render: each bench's last positions (so the live session stays put while
// pieces come and go; a reload lays the bench out afresh and the layout guarantees it looks the same), this page's moves
// still on their way, the piece being dragged, and a request from elsewhere on the page to bring a piece into view.
import { signal } from '@preact/signals';
import type { Pt } from '../model/mindmap';
import type { Pending } from '../model/placing';

const lastPositions = new Map<number, Map<number, Pt>>();

/** Bench `bench`'s positions from this page's last layout of it, by piece id; null before its first. */
export function previousOf(bench: number): ReadonlyMap<number, Pt> | null {
  return lastPositions.get(bench) ?? null;
}

/** Keeps `laid` as bench `bench`'s last positions. A pinned piece keeps the position it had before its pin, so a pin
 *  refused or later taken off puts it back where it was. */
export function remember(bench: number, laid: ReadonlyMap<number, Pt>, pinned: ReadonlySet<number>): void {
  const before = lastPositions.get(bench);
  const next = new Map<number, Pt>();
  for (const [id, at] of laid) {
    const was = before?.get(id);
    if (!pinned.has(id)) next.set(id, { x: at.x, y: at.y });
    else if (was) next.set(id, was);
  }
  lastPositions.set(bench, next);
}

/** This page's moves the server has not answered yet, by piece id. */
export const pending = signal<ReadonlyMap<number, Pending>>(new Map());

export function setPending(id: number, p: Pending | null): void {
  const next = new Map(pending.value);
  if (p) next.set(id, p);
  else next.delete(id);
  pending.value = next;
}

/** The piece being dragged and how far, in bench units, while a drag is in progress. */
export const dragging = signal<{ id: number; dx: number; dy: number; dw: number; dh: number } | null>(null);

/** A piece someone asked to see (her change, out of view); the canvas focuses it and clears this. */
export const focusAsk = signal<number | null>(null);
