// Her lines on the pieces: each of her answers on the bench's talk names the pieces her commands touched
// (`ChatConversationTurn.piece_ids`); the canvas shows her latest line beside each of those pieces, and after
// `FRESH_MS` folds it into a small "N lines" badge on the piece that opens them all. Pure.

/** How long her line stays out beside a piece before it folds into the badge. */
export const FRESH_MS = 12000;

export interface HerLine {
  turn: number;
  /** When she said it, ms since the epoch. */
  at: number;
  text: string;
  pieces: readonly number[];
}

/** Each piece's lines, latest first. `cardOf` maps a piece shown inside another's card to that card. */
export function linesByPiece(lines: readonly HerLine[], cardOf: (id: number) => number): Map<number, HerLine[]> {
  const out = new Map<number, HerLine[]>();
  for (const l of [...lines].sort((a, b) => b.at - a.at || b.turn - a.turn)) {
    for (const id of new Set(l.pieces.map(cardOf))) out.set(id, [...(out.get(id) ?? []), l]);
  }
  return out;
}

/** When each line started showing on this page, by turn: a line already there on the page's first read of the talk
 *  counts from when she said it, so a reload shows old lines as badges; one that arrives later counts from `now`, when
 *  it was seen, whatever the two clocks say. Lines `seen` already has keep their start. */
export function noteSeen(seen: ReadonlyMap<number, number>, lines: readonly HerLine[], now: number, first: boolean): Map<number, number> {
  const out = new Map(seen);
  for (const l of lines) if (!out.has(l.turn)) out.set(l.turn, first ? Math.min(l.at, now) : now);
  return out;
}

/** Whether a line that started showing at `start` is still out beside its piece at `now`. */
export function isFresh(start: number | undefined, now: number): boolean {
  return start !== undefined && now - start < FRESH_MS;
}

/** The ms until the next fresh line folds, or null when none is fresh. */
export function nextFold(seen: ReadonlyMap<number, number>, now: number): number | null {
  let soonest: number | null = null;
  for (const start of seen.values()) {
    if (!isFresh(start, now)) continue;
    const left = start + FRESH_MS - now;
    soonest = soonest === null ? left : Math.min(soonest, left);
  }
  return soonest;
}

/** What a piece's badge says. */
export function badgeText(n: number): string {
  return `${n} ${n === 1 ? 'line' : 'lines'}`;
}
