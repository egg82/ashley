// Where each card goes: the bench's cards and links turned into the mindmap layout's input (`model/placing.ts`) and laid
// out (`model/mindmap.ts`), seeded with this page's last positions of the bench (`state.ts`).
import { useMemo } from 'preact/hooks';
import type { BenchDetail, BenchPiece, PieceKind } from '../../../api/types';
import { groupDerived } from '../model/derived';
import { layoutMindmap, type Box, type MapLink, type MapPiece } from '../model/mindmap';
import { cardLinks, mapPiece, type Pending } from '../model/placing';
import { pending, previousOf, remember } from './state';

/** The goal, the bench's title, at the middle of the map. */
export const GOAL = { w: 320, h: 96 };
export const GOAL_BOX: Box = { x: -GOAL.w / 2, y: -GOAL.h / 2, w: GOAL.w, h: GOAL.h };

export interface Placement {
  cards: BenchPiece[];
  derived: ReadonlyMap<number, BenchPiece[]>;
  /** The card a piece is drawn in: its own, or its source's. */
  cardOf: (id: number) => number;
  links: MapLink[];
  /** Each laid-out card's box; a card still waiting to be measured has none yet. */
  boxes: Map<number, Box>;
  pinned: Set<number>;
}

function sourcesOf(derived: ReadonlyMap<number, BenchPiece[]>): Map<number, number> {
  const out = new Map<number, number>();
  for (const [source, pieces] of derived) for (const p of pieces) out.set(p.id, source);
  return out;
}

function place(bench: BenchDetail, kinds: ReadonlyMap<string, PieceKind>, measured: ReadonlyMap<number, number>,
               pend: ReadonlyMap<number, Pending>): Placement {
  const { cards, derived } = groupDerived(bench.pieces);
  const sources = sourcesOf(derived);
  const cardOf = (id: number) => sources.get(id) ?? id;
  const links = cardLinks(bench.links, cardOf, new Set(cards.map((p) => p.id)));
  const laid = cards.map((p) => mapPiece({ piece: p, kind: kinds.get(p.kind), measured: measured.get(p.id), pending: pend.get(p.id) }));
  const pieces = laid.filter((p): p is MapPiece => p !== null);
  const pinned = new Set(pieces.filter((p) => p.pin).map((p) => p.id));
  const previous = previousOf(bench.bench.id);
  // The first layout waits for every card, so it is the one a reload draws; after it, a card joins once it is measured.
  if (!pieces.length || (previous === null && pieces.length < cards.length)) return { cards, derived, cardOf, links, boxes: new Map(), pinned };
  const ids = new Set(pieces.map((p) => p.id));
  const boxes = layoutMindmap({ pieces, links: links.filter((l) => ids.has(l.from) && ids.has(l.to)), previous, goal: GOAL });
  remember(bench.bench.id, boxes, pinned);
  return { cards, derived, cardOf, links, boxes, pinned };
}

export function usePlacement(bench: BenchDetail, kinds: ReadonlyMap<string, PieceKind>, measured: ReadonlyMap<number, number>): Placement {
  const pend = pending.value;
  return useMemo(() => place(bench, kinds, measured, pend), [bench, kinds, measured, pend]);
}
