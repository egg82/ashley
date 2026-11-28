// One piece on the canvas, drawn in the rect its form gives (`model/fold.ts`): the piece's own card (`PieceCard`, with
// everything it does) as a full card, its header faded as a ghost, or a title chip, which glides between them. Its body
// is always drawn, hidden while it is a chip, so it is measured whatever its form (`useMeasure.ts`). A click focuses it.
import { memo } from 'preact/compat';
import type { BenchPiece, PieceKind, WorkshopKinds } from '../../../api/types';
import { drawnRect, lift, type Form } from '../model/fold';
import type { Box } from '../model/mindmap';
import { PieceCard, type PieceActions } from '../pieces/PieceCard';
import { glyphOf } from '../pieces/renderers';
import { dragging } from './state';

const CardBody = memo(PieceCard);

/** What a press on the header or chip may start a drag from: not one of the card's own controls. */
const CONTROL = 'button:not(.grip):not(.bc-chip), a, input, textarea, select, summary, label, iframe, [contenteditable]';

export interface CardProps {
  bench: number;
  piece: BenchPiece;
  kind: PieceKind | undefined;
  derived: readonly BenchPiece[];
  rules: WorkshopKinds | null;
  closed: boolean;
  act: PieceActions;
  index: number;
  count: number;
  /** Its layout box; undefined while it waits to be measured. */
  box: Box | undefined;
  width: number;
  boxed: boolean;
  form: Form;
  z: number;
  focused: boolean;
  pinned: boolean;
  landing: boolean;
  focus(id: number): void;
}

function rectOf(p: CardProps): Box | null {
  if (!p.box) return null;
  const d = dragging.value;
  const r = drawnRect(p.box, p.form, p.z);
  if (d?.id !== p.piece.id) return r;
  return { x: r.x + d.dx, y: r.y + d.dy, w: r.w + d.dw, h: r.h + d.dh };
}

function Chip({ piece, kind, k }: { piece: BenchPiece; kind: PieceKind | undefined; k: number }) {
  return (
    <button class="bc-chip" type="button" style={{ fontSize: `${12 * k}px` }} aria-label={`${piece.title}, show in full`}>
      <span class="ptype">{glyphOf(kind)}</span>
      <span class="bc-chip-title">{piece.title}</span>
    </button>
  );
}

export function CanvasCard(p: CardProps) {
  const { piece, form, box } = p;
  const r = rectOf(p);
  const k = lift(p.z);
  const d = dragging.value?.id === piece.id ? dragging.value : null;
  const id = piece.id;
  const click = (e: MouseEvent) => {
    const t = e.target as Element;
    if (!t.closest(CONTROL)) p.focus(id);
  };
  const cls = ['bc-card', `f-${form}`, p.focused && 'focus', p.pinned && 'pinned', p.landing && 'landing', d && 'dragging', !r && 'measuring'];
  const bodyW = (box && p.boxed ? box.w : p.width) + (d?.dw ?? 0);
  const bodyH = box && (p.boxed || d?.dh) ? box.h + (d?.dh ?? 0) : undefined;
  return (
    <div class={cls.filter(Boolean).join(' ')} data-card={id} data-family={p.kind?.family ?? 'unknown'}
      style={r ? { transform: `translate(${r.x}px, ${r.y}px)`, width: `${r.w}px`, height: `${r.h}px` } : { width: `${p.width}px` }}
      onClick={click}>
      <div class={`bc-body${p.boxed ? ' boxed' : ''}`} data-measure={p.boxed ? undefined : id} inert={form === 'chip'}
        style={{ width: `${bodyW}px`, height: bodyH === undefined ? undefined : `${bodyH}px` }}>
        <CardBody bench={p.bench} piece={piece} kind={p.kind} index={p.index} count={p.count} titleMax={p.rules?.title_max_chars ?? 120}
          closed={p.closed} rules={p.rules} derived={p.derived} act={p.act} />
      </div>
      {form === 'chip' && <Chip piece={piece} kind={p.kind} k={k} />}
    </div>
  );
}
