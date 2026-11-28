// Her moving the view without editing the bench (`BenchShown`, her `bench_show`): which pieces to bring into view in
// full, which to put away as chips, and where the camera goes. The camera and the held pieces are this screen's own from
// then on: a person's pan, zoom or click moves on from it.
import { focusAsk } from './state.ts';

/** Pieces her last show asked to draw in full (beside the pinned ones) and pieces it asked to put away as chips. */
export interface Held {
  full: ReadonlySet<number>;
  away: ReadonlySet<number>;
}

export const NOTHING_HELD: Held = { full: new Set(), away: new Set() };

/** What the canvas does for a show beyond the focus ask: where the camera frames (the pieces, or the whole bench) and
 *  what to hold. */
export interface Moves {
  frame(ids: readonly number[] | 'whole'): void;
  hold(held: Held): void;
}

/** Follows one show of `ids` (every piece when empty) on a bench whose laid-out pieces are `laid`; ids not laid out are
 *  dropped. One piece to see asks for focus, as a change of hers out of view does; several are framed and drawn in full;
 *  `fold` puts them away and leaves the camera where it is; the whole bench is framed (and, with `fold`, all of it put
 *  away). Moves nothing when no piece is left. */
export function show(ids: readonly number[], fold: boolean, laid: ReadonlySet<number>, move: Moves): void {
  const whole = ids.length === 0;
  const pieces = whole ? [...laid] : ids.filter((id) => laid.has(id));
  if (!pieces.length) return;
  if (fold) {
    move.hold({ full: new Set(), away: new Set(pieces) });
    if (whole) move.frame('whole');
  } else if (whole) {
    move.hold(NOTHING_HELD);
    move.frame('whole');
  } else if (pieces.length === 1) {
    move.hold(NOTHING_HELD);
    focusAsk.value = pieces[0]!;
  } else {
    move.hold({ full: new Set(pieces), away: new Set() });
    move.frame(pieces);
  }
}
