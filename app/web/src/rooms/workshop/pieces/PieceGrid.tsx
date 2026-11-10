// The bench's pieces laid out by order and size on a four-column grid, animated by piece id whenever the layout
// changes (`flip.ts`), each change marked with who made it (`marks.ts`). Reordering is by drag (`drag.ts`) or the
// grip's arrow keys; either sends one move.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { BenchDetail, BenchPiece, PieceSize, WorkshopKinds } from '../../../api/types';
import { redock } from '../../../shell/her/dock';
import { apply, stamps } from '../model/bench';
import { draftsOn } from '../model/drafts';
import { groupDerived } from '../model/derived';
import { fullIndex, inOrder, movedTo } from '../model/layout';
import { AddPiece, Orphan } from './AddPiece';
import { carried, carry, preview } from './drag';
import { animateLayout, elements, measure, type Box } from './flip';
import { away, herAt, markStamps } from './marks';
import { PieceCard, type PieceActions } from './PieceCard';

function signature(pieces: readonly BenchPiece[]): string {
  return pieces.map((p) => `${p.id}:${p.placement.size}:${p.piece_version}`).join(',');
}

function useLayoutMotion(grid: { current: HTMLDivElement | null }, shown: readonly BenchPiece[]): void {
  const last = useRef<{ boxes: Map<number, Box>; els: Map<number, HTMLElement>; sig: string } | null>(null);
  useLayoutEffect(() => {
    const g = grid.current;
    if (!g) return;
    const sig = signature(shown);
    if (last.current && last.current.sig !== sig) animateLayout(g, last.current, carried.value);
    last.current = { boxes: measure(g), els: elements(g), sig };
  });
}

/** `all` is the whole order; `ids` the part of it the screen shows, which is what indexes mean to the person. */
function actions(pieces: readonly BenchPiece[], all: readonly number[], ids: readonly number[], grid: { current: HTMLDivElement | null },
                 say: (s: string) => void): PieceActions {
  const placeAt = (piece: BenchPiece | undefined, order: number, size: PieceSize) =>
    piece ? apply({ type: 'move', piece_id: piece.id, placement: { order, size } }) : Promise.resolve();
  const find = (id: number) => pieces.find((p) => p.id === id);
  return {
    moveTo(id, to) {
      const at = fullIndex(all, ids, id, to);
      preview.value = movedTo(all, id, at);
      const piece = find(id);
      say(`${piece?.title ?? 'Piece'} moved to ${to + 1} of ${ids.length}`);
      void placeAt(piece, at, piece?.placement.size ?? 'medium').finally(() => (preview.value = null));
    },
    resize: (piece, size) => void placeAt(piece, piece.placement.order, size),
    remove: (piece) => void apply({ type: 'remove', piece_id: piece.id }),
    archive: (piece) => void apply({ type: 'archive', piece_id: piece.id }),
    grab(e, id) {
      if (grid.current) carry(e, id, grid.current, ids, (pid, to) => placeAt(find(pid), fullIndex(all, ids, pid, to), find(pid)?.placement.size ?? 'medium'));
    },
  };
}

export function pieceEl(grid: HTMLElement | null, id: number): HTMLElement | null {
  return grid?.querySelector<HTMLElement>(`:scope > [data-piece="${id}"], :scope > [data-with~="${id}"]`) ?? null;
}

/** Whether piece `id`'s header shows in the view of the column the grid scrolls in. */
export function inView(grid: HTMLElement | null, id: number): boolean {
  const el = pieceEl(grid, id);
  const view = grid?.parentElement;
  if (!view || !el) return false;
  const g = view.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return r.top >= g.top - 4 && r.top + 40 <= g.bottom;
}

interface Props {
  bench: BenchDetail;
  rules: WorkshopKinds | null;
  adding: boolean;
  doneAdding: () => void;
}

export function PieceGrid({ bench, rules, adding, doneAdding }: Props) {
  const grid = useRef<HTMLDivElement>(null);
  const [said, say] = useState('');
  const id = bench.bench.id;
  const closed = bench.bench.closed_at !== null;
  const grouped = groupDerived(bench.pieces);
  const allIds = inOrder(bench.pieces, preview.value).map((p) => p.id);
  const shown = inOrder(grouped.cards, preview.value);
  const ids = shown.map((p) => p.id);
  useLayoutMotion(grid, shown);
  useEffect(() => markStamps(stamps.value, new Set(bench.pieces.map((p) => p.id)), (p) => inView(grid.current, p)), [stamps.value]);
  useEffect(() => {
    const view = grid.current?.parentElement;
    const seen = () => away.value && inView(grid.current, away.value.piece) && (away.value = null);
    view?.addEventListener('scroll', seen, { passive: true });
    return () => view?.removeEventListener('scroll', seen);
  }, []);
  const at = herAt.value;
  useLayoutEffect(() => redock(false), [at]);
  const kinds = new Map(rules?.kinds.map((k) => [k.name, k]) ?? []);
  const act = actions(bench.pieces, allIds, ids, grid, say);
  const orphans = draftsOn(id).filter(([p]) => !bench.pieces.some((x) => x.id === p));
  return (
    <div class="pgrid" ref={grid}>
      {shown.map((p, i) => (
        <PieceCard key={p.id} bench={id} piece={p} kind={kinds.get(p.kind)} index={i} count={shown.length}
          sizes={rules?.sizes ?? [p.placement.size]} titleMax={rules?.title_max_chars ?? 120}
          closed={closed} rules={rules} derived={grouped.derived.get(p.id) ?? []} act={act} />
      ))}
      {orphans.map(([p, d]) => <Orphan key={`o${p}`} bench={id} piece={p} draft={d} />)}
      {adding && rules && <AddPiece bench={id} rules={rules} done={doneAdding} />}
      {!shown.length && !adding && !orphans.length && (
        <p class="pgrid-empty meta">{closed ? 'Nothing was left on this bench.' : bench.shelf.length ? 'Nothing out on this bench.' : 'Nothing on this bench yet. Add a piece to start.'}</p>
      )}
      <span class="sr-only" role="status">{said}</span>
    </div>
  );
}
