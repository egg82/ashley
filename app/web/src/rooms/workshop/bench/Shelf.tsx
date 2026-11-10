// The bench's shelf, under its pieces: what was archived off the layout, the most recently archived first, folded
// away with its count showing. Each piece says who archived it and when, and Restore brings it back last on the bench.
import type { BenchDetail, BenchPiece, PieceKind, WorkshopKinds } from '../../../api/types';
import { moment } from '../../memory/facts';
import { apply } from '../model/bench';
import { glyphOf } from '../pieces/renderers';

function Row({ piece, kind, room, closed }: { piece: BenchPiece; kind: PieceKind | undefined; room: boolean; closed: boolean }) {
  const hers = piece.changed_author === 'ashley';
  return (
    <li class="wshelf-row" data-family={kind?.family ?? 'unknown'}>
      <span class="ptype">{glyphOf(kind)}</span>
      <span class="wshelf-title" title={piece.title}>{piece.title}</span>
      <span class={`meta${hers ? ' her-meta' : ''}`}>archived {moment(piece.changed_at)} · {hers ? 'Ashley' : 'you'}</span>
      {!closed && (
        <button class="btn sm" type="button" disabled={!room} title={room ? undefined : 'The bench is full'}
          onClick={() => void apply({ type: 'restore', piece_id: piece.id })}>Restore</button>
      )}
    </li>
  );
}

export function Shelf({ bench, rules }: { bench: BenchDetail; rules: WorkshopKinds | null }) {
  const shelf = bench.shelf;
  if (!shelf.length) return null;
  const kinds = new Map(rules?.kinds.map((k) => [k.name, k]) ?? []);
  const room = rules === null || bench.pieces.length < rules.max_pieces;
  const closed = bench.bench.closed_at !== null;
  return (
    <details class="wshelf">
      <summary><b>Shelf</b><span class="pill">{shelf.length}</span></summary>
      <ul>
        {shelf.map((p) => <Row key={p.id} piece={p} kind={kinds.get(p.kind)} room={room} closed={closed} />)}
      </ul>
    </details>
  );
}
