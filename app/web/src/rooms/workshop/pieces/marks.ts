// Who just changed which piece, shown on it for a moment: each read's stamps mark their pieces (hers brass, the
// person's blue), and her mark goes to the piece she changed last, then back to the bench's bar. When that piece is
// scrolled out of view, a line at the edge of the pieces says what she changed and takes the person there.
import { signal } from '@preact/signals';
import type { Author, Did, Stamp } from '../model/log';

const SHOW_MS = 2600;

export interface Mark {
  by: Author;
  did: Did;
}

/** The pieces marked now, by id. */
export const marks = signal<ReadonlyMap<number, Mark>>(new Map());
/** The piece her mark sits on while she is shown changing it; null puts her back in the bar. */
export const herAt = signal<number | null>(null);
/** Her latest change to a piece out of view, until the person goes to it or it is shown. */
export const away = signal<{ piece: number; did: Did } | null>(null);

const timers = new Map<number, ReturnType<typeof setTimeout>>();
let herTimer: ReturnType<typeof setTimeout> | undefined;

function unmark(piece: number): void {
  const next = new Map(marks.value);
  next.delete(piece);
  marks.value = next;
  timers.delete(piece);
}

/** Marks each stamped piece (a removal leaves nothing to mark), and sends her mark to the last piece she changed, or
 * says where it is when `inView` says it is scrolled away. */
export function markStamps(stamps: readonly Stamp[], present: ReadonlySet<number>, inView: (piece: number) => boolean): void {
  const shown = stamps.filter((s) => present.has(s.piece));
  if (!shown.length) return;
  const next = new Map(marks.value);
  for (const s of shown) {
    next.set(s.piece, { by: s.by, did: s.did });
    clearTimeout(timers.get(s.piece));
    timers.set(s.piece, setTimeout(() => unmark(s.piece), SHOW_MS));
  }
  marks.value = next;
  const hers = shown.filter((s) => s.by === 'ashley').at(-1);
  if (!hers) return;
  if (!inView(hers.piece)) {
    away.value = { piece: hers.piece, did: hers.did };
    return;
  }
  herAt.value = hers.piece;
  clearTimeout(herTimer);
  herTimer = setTimeout(() => (herAt.value = null), SHOW_MS);
}

/** Leaving the bench: nothing stays marked. */
export function clearMarks(): void {
  timers.forEach(clearTimeout);
  timers.clear();
  clearTimeout(herTimer);
  marks.value = new Map();
  herAt.value = null;
  away.value = null;
}
