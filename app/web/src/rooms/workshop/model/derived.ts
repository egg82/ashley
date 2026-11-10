// A piece derived from another is shown inside its source's card when the source is on the bench. `RELATIONS` is the one
// extension point: a provider names the label its panel carries and reads a piece's source id from a structured field,
// never from a title or text. A transcript's source is its recording (`reader.recording`).
import type { BenchPiece } from '../../../api/types';

interface Relation {
  label: string;
  sourceOf(piece: BenchPiece): number | undefined;
}

const RELATIONS: readonly Relation[] = [
  { label: 'Transcript', sourceOf: (p) => p.reader?.recording?.piece_id },
];

/** The id of the piece `piece` is derived from, or null. */
export function sourceOf(piece: BenchPiece): number | null {
  for (const r of RELATIONS) {
    const at = r.sourceOf(piece);
    if (at !== undefined) return at;
  }
  return null;
}

/** What a derived piece's panel is called; its title for a piece no relation names. */
export function derivedLabel(piece: BenchPiece): string {
  return RELATIONS.find((r) => r.sourceOf(piece) !== undefined)?.label ?? piece.title;
}

export interface Grouped {
  /** The pieces that get a card of their own: every piece but one derived from a piece on the bench. */
  cards: BenchPiece[];
  /** Each source piece's id to the pieces derived from it, in the bench's order. */
  derived: ReadonlyMap<number, BenchPiece[]>;
}

/** A piece is shown with its source when that is another piece on `pieces` that is not itself derived. */
export function groupDerived(pieces: readonly BenchPiece[]): Grouped {
  const byId = new Map(pieces.map((p) => [p.id, p]));
  const derived = new Map<number, BenchPiece[]>();
  const cards = pieces.filter((p) => {
    const at = sourceOf(p);
    const source = at === null ? undefined : byId.get(at);
    if (!source || sourceOf(source) !== null) return true;
    derived.set(source.id, [...(derived.get(source.id) ?? []), p]);
    return false;
  });
  return { cards, derived };
}
