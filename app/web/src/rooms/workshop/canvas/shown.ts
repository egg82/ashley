// Her moving the view without editing the bench (`BenchShown`, her `bench_show`): which pieces to bring into view in
// full, which to put away as chips, and where the camera goes. The camera and the held pieces are this screen's own from
// then on: a person's pan, zoom or click moves on from it.
import { focusAsk } from './state.ts';

/** Pieces her shows asked to draw in full (beside the pinned ones) and pieces they asked to put away as chips. */
export interface Held {
  full: ReadonlySet<number>;
  away: ReadonlySet<number>;
}

export const NOTHING_HELD: Held = { full: new Set(), away: new Set() };

/** What the canvas does for a show beyond the focus ask: where the camera frames (the pieces, or the whole bench) and
 *  what to hold, as a change to what is held already. */
export interface Moves {
  frame(ids: readonly number[] | 'whole'): void;
  hold(change: (was: Held) => Held): void;
}

/** `held` with `pieces` drawn in full (`full`) or put away, and no longer the other. */
function holding(held: Held, pieces: readonly number[], full: boolean): Held {
  const rest = (set: ReadonlySet<number>) => [...set].filter((id) => !pieces.includes(id));
  return full
    ? { full: new Set([...held.full, ...pieces]), away: new Set(rest(held.away)) }
    : { full: new Set(rest(held.full)), away: new Set([...held.away, ...pieces]) };
}

/** Follows one show of `ids` (every piece when empty) on a bench whose laid-out pieces are `laid`; ids not laid out are
 *  dropped. One piece to see asks for focus, as a change of hers out of view does; several are framed and drawn in full;
 *  `fold` puts them away and leaves the camera where it is; the whole bench is framed and released from earlier shows
 *  (with `fold`, all of it put away). Moves nothing when no piece is left. */
export function show(ids: readonly number[], fold: boolean, laid: ReadonlySet<number>, move: Moves): void {
  const whole = ids.length === 0;
  const pieces = whole ? [...laid] : ids.filter((id) => laid.has(id));
  if (!pieces.length) return;
  if (fold) {
    move.hold((was) => holding(was, pieces, false));
    if (whole) move.frame('whole');
  } else if (whole) {
    move.hold(() => NOTHING_HELD);
    move.frame('whole');
  } else {
    move.hold((was) => holding(was, pieces, true));
    if (pieces.length === 1) focusAsk.value = pieces[0]!;
    else move.frame(pieces);
  }
}
