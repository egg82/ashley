// Seeded benches and measures for the mindmap layout's tests.
import { GAP, layoutMindmap, type Box, type LinkKind, type MapLink, type MapPiece, type MindmapInput, type Pt } from './mindmap.ts';

export const GOAL = { w: 360, h: 200 };

export function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface Bench {
  pieces: MapPiece[];
  links: MapLink[];
}

/** Piece `i`'s pin when it has one: three far, well-apart spots, so pins never touch each other. */
function pinFor(i: number): Pt | null {
  if (i % 20 !== 5) return null;
  const k = (i - 5) / 20;
  const t = 0.5 + k * 2.09;
  const r = 1300 + 150 * k;
  return { x: Math.round(r * Math.cos(t)), y: Math.round(r * Math.sin(t)) };
}

/** A random tree (ids 1..n, each linked to an earlier piece, a few left unlinked) plus cross links, mixed sizes. */
export function makeBench(seed: number, n: number): Bench {
  const rnd = prng(seed);
  const pieces: MapPiece[] = [];
  const links: MapLink[] = [];
  const kinds: LinkKind[] = ['part_of', 'part_of', 'part_of', 'depends_on', 'version_of'];
  for (let i = 1; i <= n; i++) {
    const size = { w: 160 + Math.floor(rnd() * 361), h: 80 + Math.floor(rnd() * 321) };
    pieces.push({ id: i, order: i, size, pin: pinFor(i) });
    if (i > 1 && rnd() > 0.1) links.push({ from: i, kind: kinds[Math.floor(rnd() * kinds.length)]!, to: 1 + Math.floor(rnd() * (i - 1)) });
  }
  for (let c = 0; c < n / 5; c++) {
    const from = 2 + Math.floor(rnd() * (n - 1));
    const to = 1 + Math.floor(rnd() * (from - 1));
    links.push({ from, kind: 'depends_on', to });
  }
  return { pieces, links };
}

export const input = (b: Bench, previous: Map<number, Box> | null): MindmapInput => ({
  pieces: b.pieces,
  links: b.links,
  previous,
  goal: GOAL,
});

export const lay = (b: Bench, previous: Map<number, Box> | null = null): Map<number, Box> => layoutMindmap(input(b, previous));

/** Problems with a layout, as text: boxes closer than GAP, a moved pin, a missing or resized piece. Empty when sound. */
export function faults(b: Bench, got: Map<number, Box>): string[] {
  const out: string[] = [];
  const goal = { x: -GOAL.w / 2, y: -GOAL.h / 2, ...GOAL };
  const all: [string, Box, boolean][] = [['goal', goal, true]];
  for (const p of b.pieces) {
    const box = got.get(p.id);
    if (!box) {
      out.push(`piece ${p.id} has no box`);
      continue;
    }
    if (box.w !== p.size.w || box.h !== p.size.h) out.push(`piece ${p.id} was resized`);
    if (p.pin && (box.x !== p.pin.x || box.y !== p.pin.y)) out.push(`pin ${p.id} moved`);
    all.push([`piece ${p.id}`, box, !!p.pin]);
  }
  for (let i = 0; i < all.length; i++) {
    for (let j = i + 1; j < all.length; j++) {
      const [na, a, pa] = all[i]!;
      const [nb, c, pb] = all[j]!;
      if (pa && pb) continue;
      const dx = Math.max(a.x - (c.x + c.w), c.x - (a.x + a.w));
      const dy = Math.max(a.y - (c.y + c.h), c.y - (a.y + a.h));
      if (Math.max(dx, dy) < GAP) out.push(`${na} and ${nb} are within ${GAP}`);
    }
  }
  return out;
}

/** The farthest any unpinned piece in both layouts moved (top-left), in px. */
export function worstMove(before: Map<number, Box>, after: Map<number, Box>, b: Bench): number {
  let worst = 0;
  for (const p of b.pieces) {
    const x = before.get(p.id);
    const y = after.get(p.id);
    if (!x || !y || p.pin) continue;
    worst = Math.max(worst, Math.hypot(x.x - y.x, x.y - y.y));
  }
  return worst;
}

const mid = (b: Box): Pt => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });

/** Mean centre distance over the links. */
export function meanLinkLength(links: readonly MapLink[], got: Map<number, Box>): number {
  let sum = 0;
  for (const l of links) {
    const a = mid(got.get(l.from)!);
    const c = mid(got.get(l.to)!);
    sum += Math.hypot(a.x - c.x, a.y - c.y);
  }
  return sum / links.length;
}

/** The same boxes with the positions dealt out among them by a seeded shuffle: same footprint, links ignored. */
export function shuffled(got: Map<number, Box>, seed: number): Map<number, Box> {
  const rnd = prng(seed);
  const ids = [...got.keys()];
  const spots = ids.map((id) => ({ x: got.get(id)!.x, y: got.get(id)!.y }));
  for (let i = spots.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [spots[i], spots[j]] = [spots[j]!, spots[i]!];
  }
  return new Map(ids.map((id, i) => [id, { ...got.get(id)!, ...spots[i]! }]));
}
