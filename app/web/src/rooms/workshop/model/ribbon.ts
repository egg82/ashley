// Where the bench's talk shows once the transcript column is gone: one dot per line on the ribbon, in the order said,
// and her new answer on the voice bar: its words when it touched no piece, or which piece it is on (the words are that
// piece's callout on the canvas). Pure.

/** A line of the bench's talk, as far as the ribbon cares. */
export interface TalkLine {
  key: string;
  author: 'person' | 'ashley' | 'household';
  text: string;
  turn?: number;
  missed?: unknown;
}

export interface Dot {
  key: string;
  /** The stored turn, which the talk in order scrolls to; unset on a line only this page knows yet. */
  turn?: number;
  who: 'her' | 'you';
  text: string;
  /** The piece a tap flies to: the first piece her answer touched that is still on the bench; null opens the talk. */
  piece: number | null;
  missed: boolean;
}

/** How many dots the ribbon draws; earlier lines are counted, not drawn. */
export const RIBBON_MAX = 12;

/** The ribbon's dots, the latest `max` lines in order, and how many earlier lines it does not draw. `touched` is each
 *  of her turns' piece ids; `onBench` says whether a piece is out on the bench now. */
export function ribbonOf(lines: readonly TalkLine[], touched: ReadonlyMap<number, readonly number[]>,
  onBench: (id: number) => boolean, max = RIBBON_MAX): { dots: Dot[]; earlier: number } {
  const all = lines.flatMap((l): Dot[] => {
    if (l.author === 'household') return [];
    const pieces = l.author === 'ashley' && l.turn !== undefined ? touched.get(l.turn) ?? [] : [];
    return [{ key: l.key, ...(l.turn !== undefined && { turn: l.turn }), who: l.author === 'ashley' ? 'her' : 'you', text: l.text, piece: pieces.find(onBench) ?? null, missed: !!l.missed }];
  });
  const dots = all.slice(Math.max(0, all.length - max));
  return { dots, earlier: all.length - dots.length };
}

/** Her answer the voice bar shows: the talk's last line, when it is hers and came while this page was open (it is not
 *  in `firstRead`, the turns of the page's first read), with the first piece on the bench it touched, or null for
 *  none. Null when there is no such answer. */
export function barLine(lines: readonly TalkLine[], touched: ReadonlyMap<number, readonly number[]>,
  onBench: (id: number) => boolean, firstRead: ReadonlySet<number>): { line: TalkLine; piece: number | null } | null {
  const last = lines.at(-1);
  if (!last || last.author !== 'ashley' || !last.text) return null;
  if (last.turn !== undefined && firstRead.has(last.turn)) return null;
  const pieces = last.turn !== undefined ? touched.get(last.turn) ?? [] : [];
  return { line: last, piece: pieces.find(onBench) ?? null };
}
