// Where her line or its badge sits beside a piece on the canvas: in free space, never over another piece or the goal.
// Pure. Boxes are bench units: the layout's boxes (`mindmap.ts`) are the obstacles, so a piece's whole box counts even
// while it is folded to a chip; the anchor is the rect the piece is drawn in, so a chip's badge may sit in its own
// box's spare room.
import type { Box } from './mindmap.ts';

export type Side = 'right' | 'left' | 'above' | 'below';
export const SIDES: readonly Side[] = ['right', 'left', 'above', 'below'];

/** Px at zoom 1: her line out beside a piece, at most this big; a badge's height and its width per character. */
export const SAYS = { w: 300, h: 72 };
const BADGE_H = 22;
const BADGE_PAD = 20;
const BADGE_CHAR = 7.5;
const GAP = 6;

export function badgeSize(text: string): { w: number; h: number } {
  return { w: BADGE_PAD + BADGE_CHAR * text.length, h: BADGE_H };
}

const touches = (a: Box, b: Box): boolean => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function at(anchor: Box, size: { w: number; h: number }, side: Side, gap: number): Box {
  if (side === 'right') return { x: anchor.x + anchor.w + gap, y: anchor.y, ...size };
  if (side === 'left') return { x: anchor.x - gap - size.w, y: anchor.y, ...size };
  if (side === 'above') return { x: anchor.x, y: anchor.y - gap - size.h, ...size };
  return { x: anchor.x, y: anchor.y + anchor.h + gap, ...size };
}

/** The first side of `anchor` where a box of `size` (px at zoom 1, drawn `k` times larger) touches none of `obstacles`;
 *  null when none is clear. */
export function aside(anchor: Box, size: { w: number; h: number }, k: number, obstacles: readonly Box[]): Box | null {
  const s = { w: size.w * k, h: size.h * k };
  for (const side of SIDES) {
    const b = at(anchor, s, side, GAP * k);
    if (!obstacles.some((o) => touches(b, o))) return b;
  }
  return null;
}

export interface AsideWant {
  id: number;
  /** The rect the piece is drawn in. */
  anchor: Box;
  /** Her line's text while it is out beside the piece, else null (a badge only). */
  says: string | null;
  badge: string;
}

/** `inside`: a badge with no clear side, in its own piece's corner. */
export interface Placed {
  kind: 'says' | 'badge' | 'inside';
  box: Box;
}

/** Where each piece's line or badge goes, in id order, each placed one an obstacle for the next. A line with no clear
 *  side folds to its badge at once; a badge with no clear side sits inside its own piece's top right corner, over the
 *  piece itself and nothing else. `boxes` are the pieces' layout boxes by id; `fixed` the rest of the map (the goal). */
export function placeAsides(wants: readonly AsideWant[], boxes: ReadonlyMap<number, Box>, fixed: readonly Box[], k: number): Map<number, Placed> {
  const taken: Box[] = [...fixed];
  const out = new Map<number, Placed>();
  for (const w of [...wants].sort((a, b) => a.id - b.id)) {
    const others = [...taken, ...[...boxes].filter(([id]) => id !== w.id).map(([, b]) => b)];
    const says = w.says === null ? null : aside(w.anchor, SAYS, k, others);
    const badge = says ? null : aside(w.anchor, badgeSize(w.badge), k, others);
    const placed: Placed = says ? { kind: 'says', box: says } : badge ? { kind: 'badge', box: badge }
      : { kind: 'inside', box: insideCorner(w.anchor, badgeSize(w.badge), k) };
    out.set(w.id, placed);
    if (placed.kind !== 'inside') taken.push(placed.box);
  }
  return out;
}

function insideCorner(anchor: Box, size: { w: number; h: number }, k: number): Box {
  const w = Math.min(anchor.w, size.w * k);
  const h = Math.min(anchor.h, size.h * k);
  return { x: anchor.x + anchor.w - w, y: anchor.y, w, h };
}
