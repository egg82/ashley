// Her lines on the pieces (`model/herLines.ts`): her latest line out beside each piece her answer touched, then, after a
// while, an "N lines" badge on the piece that opens every line of hers about it.
import { useEffect, useMemo, useState } from 'preact/hooks';
import { moment } from '../../memory/facts';
import { badgeText, isFresh, linesByPiece, nextFold, noteSeen, type HerLine } from '../model/herLines';
import { talkPieceLines, talkState } from '../model/talk';

const seenByBench = new Map<number, ReadonlyMap<number, number>>();

export interface HerLinesNow {
  byPiece: ReadonlyMap<number, HerLine[]>;
  /** Whether piece `id`'s latest line is out beside it now: while it is fresh, and beside the first of the pieces it
   *  touched that is on the bench (the others show the badge), so one answer is not repeated across the map. */
  fresh(id: number): boolean;
}

export function useHerLines(bench: number, cardOf: (id: number) => number, present: ReadonlySet<number>): HerLinesNow {
  const lines = talkPieceLines.value;
  const ready = talkState.value === 'ready';
  const [now, setNow] = useState(() => Date.now());
  const seen = useMemo(() => {
    const was = seenByBench.get(bench);
    if (!ready) return was ?? new Map<number, number>();
    const next = noteSeen(was ?? new Map(), lines, Date.now(), was === undefined);
    seenByBench.set(bench, next);
    return next;
  }, [bench, lines, ready]);
  useEffect(() => {
    const wait = nextFold(seen, Date.now());
    if (wait === null) return;
    const timer = setTimeout(() => setNow(Date.now()), wait + 20);
    return () => clearTimeout(timer);
  }, [seen, now]);
  const byPiece = useMemo(() => linesByPiece(lines, cardOf), [lines, cardOf]);
  const fresh = (id: number) => {
    const line = byPiece.get(id)?.[0];
    return !!line && isFresh(seen.get(line.turn), Date.now()) && line.pieces.map(cardOf).find((p) => present.has(p)) === id;
  };
  return { byPiece, fresh };
}

/** Her latest line, out beside the piece above its top edge, `k` times its size so it stays readable. */
export function Says({ line, k }: { line: HerLine; k: number }) {
  return (
    <p class="bc-says" style={{ transform: `scale(${k})` }}>
      <b>Ashley</b>{line.text}
    </p>
  );
}

/** The badge on a piece her lines are about, which opens them, latest first. */
export function LinesBadge({ lines, k }: { lines: readonly HerLine[]; k: number }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => !(e.target instanceof Element && e.target.closest('.bc-lines')) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open]);
  return (
    <div class="bc-lines" style={{ transform: `scale(${k})` }}>
      <button class="bc-badge" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{badgeText(lines.length)}</button>
      {open && (
        <ol class="bc-thread" aria-label="Her lines about this piece">
          {lines.map((l) => (
            <li key={l.turn}><span class="meta">{moment(new Date(l.at).toISOString())}</span>{l.text}</li>
          ))}
        </ol>
      )}
    </div>
  );
}
