// Which pieces a bench canvas draws in full and which it folds to a title chip, and the rect each is drawn in. Pure.
//
// The rule is readability: no text a person reads is drawn below `READ_FLOOR_PX` on screen. A full card's smallest
// reading text is `CARD_TEXT_PX`, so cards are drawn only at a zoom that keeps it at the floor; past that everything
// folds to chips. At a zoom where cards are readable, the focus and the pieces one link away (`foldDistance`) draw in
// full, so do pinned pieces (a person put them there to look at), and the rest fold. A piece a newer one is a version
// of draws as a faded header (`ghost`) beside it. A chip keeps its title at the floor at any zoom by drawing larger in
// bench units as the camera pulls back, inside the piece's box, so chips never overlap; the camera never pulls back
// past the zoom where the narrowest chip would be too narrow to hold a title (`minZoom`).
import { foldDistance, type Box, type MapLink } from './mindmap.ts';

export const READ_FLOOR_PX = 12;
/** The smallest text a full card draws (code and tables), in px at zoom 1. */
export const CARD_TEXT_PX = 12;
/** A chip's title, in px at zoom 1. */
export const CHIP_TEXT_PX = 12;
/** A chip on screen: as wide as `w` at most (narrower when its box is), never narrower than `minW`, `h` high. */
export const CHIP = { w: 220, minW: 120, h: 30 };
/** A ghost's header, in px at zoom 1. */
export const GHOST_H = 38;
/** The furthest a camera may pull back whatever the pieces. */
const Z_FLOOR = 0.2;

export type Form = 'card' | 'chip' | 'ghost';

/** Whether a full card's text is readable at zoom `z`. */
export function cardsReadable(z: number): boolean {
  return z * CARD_TEXT_PX >= READ_FLOOR_PX - 1e-9;
}

/** How much larger than its zoom-1 size a chip or a label draws in bench units at zoom `z`, so its text stays at the
 *  floor: 1 while the zoom keeps it there, more as the camera pulls back. */
export function lift(z: number): number {
  return Math.max(1, READ_FLOOR_PX / (CHIP_TEXT_PX * z));
}

export interface FoldInput {
  ids: readonly number[];
  /** The piece in focus; null draws every piece in full. */
  focus: number | null;
  links: readonly MapLink[];
  pinned: ReadonlySet<number>;
  /** Pieces a newer piece on the bench is a version of. */
  superseded: ReadonlySet<number>;
  /** Pieces she asked to put away: chips whatever else would draw them in full. */
  away?: ReadonlySet<number>;
  z: number;
}

/** Each piece's form. */
export function formsOf(f: FoldInput): Map<number, Form> {
  const readable = cardsReadable(f.z);
  const hops = f.focus === null ? null : foldDistance(f.focus, f.links);
  const out = new Map<number, Form>();
  for (const id of f.ids) {
    if (!readable || f.away?.has(id)) out.set(id, 'chip');
    else if (id === f.focus) out.set(id, 'card');
    else if (f.superseded.has(id)) out.set(id, 'ghost');
    else if (f.pinned.has(id) || !hops) out.set(id, 'card');
    else out.set(id, (hops.get(id) ?? Infinity) <= 1 ? 'card' : 'chip');
  }
  return out;
}

/** The rect a piece with layout box `box` is drawn in: the box for a card, its top as a header for a ghost, and for a
 *  chip a pill centred in the box. */
export function drawnRect(box: Box, form: Form, z: number): Box {
  if (form === 'card') return box;
  const k = lift(z);
  if (form === 'ghost') return { x: box.x, y: box.y, w: box.w, h: Math.min(box.h, GHOST_H * k) };
  const w = Math.min(box.w, CHIP.w * k);
  const h = Math.min(box.h, CHIP.h * k);
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h };
}

/** The furthest out the camera may zoom: where the narrowest box still holds a chip `CHIP.minW` wide and the shortest
 *  one a chip `CHIP.h` high, and never past 1 (a bench of wide pieces can still be drawn whole). */
export function minZoom(sizes: readonly { w: number; h: number }[]): number {
  let z = Z_FLOOR;
  for (const s of sizes) z = Math.max(z, CHIP.minW / s.w, CHIP.h / s.h);
  return Math.min(1, z);
}

/** The pieces another piece on the bench is a version of (`from` is a version of `to`, so `to` is the old one). */
export function supersededBy(links: readonly MapLink[], ids: ReadonlySet<number>): Set<number> {
  const out = new Set<number>();
  for (const l of links) if (l.kind === 'version_of' && ids.has(l.from) && ids.has(l.to)) out.add(l.to);
  return out;
}
