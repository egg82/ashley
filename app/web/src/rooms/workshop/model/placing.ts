// From a bench as the server sends it to the mindmap layout's input (`mindmap.ts`): which pieces get a card (a piece
// derived from another is drawn inside its source's card, `derived.ts`), the links between cards, each card's size
// (the person's box, else its measured content at its kind's width), and its pin, with this page's moves still on their
// way laid over the server's. Pure.
import type { BenchLink, BenchPiece, PieceKind } from '../../../api/types';
import { isModel } from '../pieces/modelFacts.ts';
import type { LinkKind, MapLink, MapPiece, Pt } from './mindmap.ts';

/** A card's width when the person has not given it a box, by what its body is. */
const WIDE = 440;
const MID = 360;
const NARROW = 300;
const WIDE_FORMATS: ReadonlySet<PieceKind['format']> = new Set(['code', 'automation', 'diagram', 'site', 'video', 'reader', 'recipe', 'session', 'job', 'image', 'file', 'clip', 'audio']);

export function cardWidth(kind: PieceKind | undefined): number {
  if (!kind) return MID;
  if (isModel(kind) || WIDE_FORMATS.has(kind.format) || kind.family === 'large') return WIDE;
  return kind.format === 'plain' ? NARROW : MID;
}

const LINK_KINDS: ReadonlySet<string> = new Set<LinkKind>(['part_of', 'depends_on', 'version_of']);

/** The links between cards: a link to a piece drawn inside another's card ends at that card; one that ends where it
 *  starts, one of a kind this page does not draw, and repeats are left out. */
export function cardLinks(links: readonly BenchLink[], cardOf: (id: number) => number, cards: ReadonlySet<number>): MapLink[] {
  const seen = new Set<string>();
  const out: MapLink[] = [];
  for (const l of links) {
    const from = cardOf(l.from_id);
    const to = cardOf(l.to_id);
    const key = `${from}:${l.kind}:${to}`;
    if (from === to || !LINK_KINDS.has(l.kind) || !cards.has(from) || !cards.has(to) || seen.has(key)) continue;
    seen.add(key);
    out.push({ from, kind: l.kind as LinkKind, to });
  }
  return out;
}

/** A move of this page's that the server has not answered yet: the pin and box it sets (undefined keeps the piece's). */
export interface Pending {
  pin?: Pt | null;
  box?: { w: number; h: number } | null;
}

/** Where a piece is pinned and how big a box it was given, with `pending` laid over the server's. */
export function placeOf(piece: BenchPiece, pending: Pending | undefined): { pin: Pt | null; box: { w: number; h: number } | null } {
  const pin = pending?.pin !== undefined ? pending.pin : piece.placement.pin ?? null;
  const box = pending?.box !== undefined ? pending.box : piece.placement.box ?? null;
  return { pin, box };
}

export interface CardInput {
  piece: BenchPiece;
  kind: PieceKind | undefined;
  /** Its content's height measured at its width; undefined while not measured yet. */
  measured: number | undefined;
  pending: Pending | undefined;
}

/** The layout's piece for a card, or null while it waits to be measured (a boxed card needs no measuring). */
export function mapPiece(c: CardInput): MapPiece | null {
  const { pin, box } = placeOf(c.piece, c.pending);
  if (box) return { id: c.piece.id, order: c.piece.placement.order, size: { w: box.w, h: box.h }, pin };
  if (c.measured === undefined) return null;
  return { id: c.piece.id, order: c.piece.placement.order, size: { w: cardWidth(c.kind), h: Math.ceil(c.measured) }, pin };
}

/** A pin or box as the server takes it: whole bench units. */
export const wholePt = (p: Pt): Pt => ({ x: Math.round(p.x), y: Math.round(p.y) });

/** A box held to the bench's bounds (`workshop.json`'s `layout`, which the server checks again). */
export function heldBox(w: number, h: number): { w: number; h: number } {
  return { w: Math.round(Math.min(2400, Math.max(160, w))), h: Math.round(Math.min(2400, Math.max(80, h))) };
}
