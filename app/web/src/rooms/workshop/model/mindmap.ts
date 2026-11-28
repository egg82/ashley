// A bench drawn as a mindmap: positions from the links between pieces, the goal at the origin. Pure, no DOM, no
// randomness. Positions are TOP-LEFT corners, in bench units (px), and `pin` is a top-left corner too.
//
// Placement is a single greedy pass over a growing set of obstacles: the goal, then pinned pieces (exactly where
// pinned), then pieces that have a previous position (kept there if clear, else moved to the nearest clear slot),
// then the rest in ID order (ids only grow, so a newer piece has a higher id). Each goes to the cheapest clear slot
// searched outward from the piece it links to, counting only links to LOWER ids (or from the goal, by golden angle of
// its order, when it has none). A pin placed up front is ignored while choosing a lower id's slot, unless the slot
// would touch it, so a pin does not change where earlier pieces went.
//
// Consequences. A valid previous layout never moves: adding or removing a piece, or a link, displaces nothing. And a
// layout with `previous = null` reproduces the one grown piece by piece, so a reload, another screen or another
// device draws the bench as the open screen did. The two can still differ after: a removal (the gap stays in the grown
// one, is filled in the fresh one), a resize, a pin dropped on a piece (that piece moves), a reorder (the order
// ranks pieces that link to nothing), and a link added after the piece it leaves (the grown layout never saw it).
export type LinkKind = 'part_of' | 'depends_on' | 'version_of';

export interface MapPiece {
  id: number;
  /** Reading order. */
  order: number;
  /** Measured content size, or the person's box. */
  size: { w: number; h: number };
  pin: Pt | null;
}
export interface MapLink {
  from: number;
  kind: LinkKind;
  to: number;
}
export interface Pt {
  x: number;
  y: number;
}
export interface Box extends Pt {
  w: number;
  h: number;
}
export interface MindmapInput {
  pieces: readonly MapPiece[];
  links: readonly MapLink[];
  /** The positions of the last pass, by piece id. */
  previous: ReadonlyMap<number, Pt> | null;
  goal: { w: number; h: number };
}

/** The clear space kept between any two boxes. */
export const GAP = 24;
const STEP = 24;
const ANGLES = 36;
const MAX_RINGS = 400;
const EXTRA_RINGS = 2;
const GOLDEN = 2.399963229728653;
const TURN_ROOT = 300;
const TURN_CHILD = 80;
// A piece lands beside a version first, then under a parent, then near what it depends on.
const KIND_RANK: Record<LinkKind, number> = { version_of: 0, part_of: 1, depends_on: 2 };

interface Want {
  at: Pt;
  pull: Pt[];
  facing: number | null;
  turn: number;
}

const centre = (b: Box): Pt => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });
const dist = (a: Pt, b: Pt): number => Math.hypot(a.x - b.x, a.y - b.y);

function angleBetween(a: number, b: number): number {
  const d = (((a - b) % (2 * Math.PI)) + 3 * Math.PI) % (2 * Math.PI);
  return Math.abs(d - Math.PI);
}

function clear(b: Box, placed: readonly Box[]): boolean {
  for (const o of placed) {
    if (b.x < o.x + o.w + GAP && o.x < b.x + b.w + GAP && b.y < o.y + o.h + GAP && o.y < b.y + b.h + GAP) return false;
  }
  return true;
}

function costOf(c: Pt, want: Want): number {
  let cost = 0;
  for (const p of want.pull) cost += dist(c, p);
  if (want.facing !== null) {
    cost += (want.turn * angleBetween(Math.atan2(c.y - want.at.y, c.x - want.at.x), want.facing)) / Math.PI;
  }
  return cost;
}

/** The cheapest clear top-left for a box of `size`, on rings searched outward from `want.at`. */
function slotFor(size: { w: number; h: number }, want: Want, placed: readonly Box[]): Pt {
  let best: Pt | null = null;
  let bestCost = Infinity;
  let rings = EXTRA_RINGS + 1;
  for (let k = 1; k <= MAX_RINGS && rings > 0; k++) {
    let found = false;
    for (let a = 0; a < ANGLES; a++) {
      const t = (a * 2 * Math.PI) / ANGLES;
      const c = { x: want.at.x + STEP * k * Math.cos(t), y: want.at.y + STEP * k * Math.sin(t) };
      const box = { x: c.x - size.w / 2, y: c.y - size.h / 2, w: size.w, h: size.h };
      if (!clear(box, placed)) continue;
      found = true;
      const cost = costOf(c, want);
      if (cost < bestCost) {
        bestCost = cost;
        best = { x: box.x, y: box.y };
      }
    }
    if (found) rings--;
  }
  return best ?? { x: want.at.x + STEP * MAX_RINGS, y: want.at.y };
}

/** Each piece's links to pieces with a lower id that are on the bench, best kind first. */
function parentsOf(ids: ReadonlySet<number>, links: readonly MapLink[]): Map<number, MapLink[]> {
  const out = new Map<number, MapLink[]>();
  for (const l of links) {
    if (!ids.has(l.from) || !ids.has(l.to) || l.to >= l.from) continue;
    out.set(l.from, [...(out.get(l.from) ?? []), l]);
  }
  for (const ls of out.values()) ls.sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.to - b.to);
  return out;
}

/** Hops along links, either way, from `focusId` to each piece the links reach. The view draws 0 and 1 in full and folds
 *  the rest to title chips; a piece the focus cannot reach is absent. */
export function foldDistance(focusId: number, links: readonly MapLink[]): Map<number, number> {
  const next = new Map<number, number[]>();
  for (const l of links) {
    next.set(l.from, [...(next.get(l.from) ?? []), l.to]);
    next.set(l.to, [...(next.get(l.to) ?? []), l.from]);
  }
  const hops = new Map<number, number>([[focusId, 0]]);
  const queue = [focusId];
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i]!;
    for (const n of next.get(id) ?? []) {
      if (hops.has(n)) continue;
      hops.set(n, hops.get(id)! + 1);
      queue.push(n);
    }
  }
  return hops;
}

interface Ctx {
  parents: Map<number, MapLink[]>;
  boxes: Map<number, Box>;
  rank: Map<number, number>;
}

/** Where a new piece wants to go: beside the lower-id piece it links to first, pulled toward all of them. */
function wantFor(p: MapPiece, ctx: Ctx): Want {
  const outs = ctx.parents.get(p.id) ?? [];
  const pull = outs.map((l) => centre(ctx.boxes.get(l.to)!));
  const first = outs[0];
  if (first) {
    const at = pull[0]!;
    const outward = Math.hypot(at.x, at.y) < 1 ? null : Math.atan2(at.y, at.x);
    return { at, pull, facing: first.kind === 'version_of' ? 0 : outward, turn: TURN_CHILD };
  }
  const origin = { x: 0, y: 0 };
  return { at: origin, pull: [origin], facing: -Math.PI / 2 + GOLDEN * ctx.rank.get(p.id)!, turn: TURN_ROOT };
}

/** The slot ignoring pins of higher ids, unless that slot touches one; then the slot among everything placed. */
function slotAmong(p: MapPiece, want: Want, placed: readonly Box[], pins: ReadonlyMap<number, Box>): Pt {
  const ahead = new Set([...pins].filter(([id]) => id > p.id).map(([, b]) => b));
  const early = placed.filter((b) => !ahead.has(b));
  const at = slotFor(p.size, want, early);
  const box = { x: at.x, y: at.y, w: p.size.w, h: p.size.h };
  return clear(box, placed) ? at : slotFor(p.size, want, placed);
}

const byOrder = (a: MapPiece, b: MapPiece): number => a.order - b.order || a.id - b.id;

/** Each piece's top-left and size. Pins stay exactly where pinned; a piece with a clear previous position stays there;
 *  the rest are placed by their links. No two boxes, nor a box and the goal, come within `GAP` of each other (a pin
 *  the person put on the goal or on another pin is theirs to keep). */
export function layoutMindmap(inp: MindmapInput): Map<number, Box> {
  const sorted = [...inp.pieces].sort(byOrder);
  const goal = { x: -inp.goal.w / 2, y: -inp.goal.h / 2, w: inp.goal.w, h: inp.goal.h };
  const placed: Box[] = [goal];
  const boxes = new Map<number, Box>();
  const put = (p: MapPiece, at: Pt): void => {
    const box = { x: at.x, y: at.y, w: p.size.w, h: p.size.h };
    boxes.set(p.id, box);
    placed.push(box);
  };
  for (const p of sorted) if (p.pin) put(p, p.pin);
  for (const p of sorted) {
    const was = p.pin ? undefined : inp.previous?.get(p.id);
    if (!was) continue;
    const here = { x: was.x, y: was.y, w: p.size.w, h: p.size.h };
    if (clear(here, placed)) put(p, was);
    else {
      const c = centre(here);
      put(p, slotFor(p.size, { at: c, pull: [c], facing: null, turn: 0 }, placed));
    }
  }
  const parents = parentsOf(new Set(sorted.map((p) => p.id)), inp.links);
  const ctx: Ctx = { parents, boxes, rank: new Map(sorted.map((p, i) => [p.id, i])) };
  const later = new Map(sorted.filter((p) => p.pin).map((p) => [p.id, boxes.get(p.id)!]));
  for (const p of [...sorted].sort((a, b) => a.id - b.id)) {
    if (boxes.has(p.id)) continue;
    put(p, slotAmong(p, wantFor(p, ctx), placed, later));
  }
  return boxes;
}
