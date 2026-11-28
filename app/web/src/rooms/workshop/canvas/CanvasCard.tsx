// One piece on the canvas, drawn in the rect its form gives (`model/fold.ts`): the piece's own card (`PieceCard`, with
// everything it does) as a full card, its header faded as a ghost, or a title chip, which glides between them. Its body
// is always drawn at its natural height inside a clip the size of the drawn rect (hidden while it is a chip), so it is
// measured whatever its form (`useMeasure.ts`). Dragging the header
// or the chip pins it, the corner resizes it (`pinDrag.ts`), the pin hands it back to the layout, and a click focuses
// it. Her line about it sits beside it, then its badge (`HerLines.tsx`).
import { memo } from 'preact/compat';
import type { BenchPiece, PieceKind, WorkshopKinds } from '../../../api/types';
import { drawnRect, lift, type Form } from '../model/fold';
import type { Placed } from '../model/aside';
import type { HerLine } from '../model/herLines';
import type { Box } from '../model/mindmap';
import { PieceCard, type PieceActions } from '../pieces/PieceCard';
import { glyphOf } from '../pieces/renderers';
import { LinesBadge, Says } from './HerLines';
import { press, sendPlace } from './pinDrag';
import { hovered, marked, tapped } from '../model/pointing';
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
  lines: readonly HerLine[] | undefined;
  /** Where her line or its badge sits (`model/aside.ts`), in bench units. */
  aside: Placed | undefined;
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

function Pin({ piece }: { piece: BenchPiece }) {
  return (
    <button class="bc-pin" type="button" title="Pinned. Hand back to the layout" aria-label={`Unpin ${piece.title}`}
      onClick={() => sendPlace(piece, { pin: null })}>
      <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4 1h4l-.6 3.4L9.5 6.5H6.6L6 11 5.4 6.5H2.5l2.1-2.1z" /></svg>
    </button>
  );
}

export function CanvasCard(p: CardProps) {
  const { piece, form, box } = p;
  const r = rectOf(p);
  const k = lift(p.z);
  const d = dragging.value?.id === piece.id ? dragging.value : null;
  const id = piece.id;
  const down = (e: PointerEvent) => {
    const t = e.target as Element;
    if (!box || !t.closest('header, .bc-chip') || t.closest(CONTROL)) return;
    if (p.closed) return;
    press(e, piece, box, p.z, false, () => p.focus(id));
  };
  const click = (e: MouseEvent) => {
    const t = e.target as Element;
    tapped.value = id;
    if (!t.closest(CONTROL)) p.focus(id);
  };
  const cls = ['bc-card', `f-${form}`, p.focused && 'focus', p.pinned && 'pinned', p.landing && 'landing', marked.value === id && 'pointed', d && 'dragging', !r && 'measuring'];
  const bodyW = (box && p.boxed ? box.w : p.width) + (d?.dw ?? 0);
  const bodyH = box && (p.boxed || d?.dh) ? box.h + (d?.dh ?? 0) : undefined;
  return (
    <div class={cls.filter(Boolean).join(' ')} data-card={id} data-family={p.kind?.family ?? 'unknown'}
      style={r ? { transform: `translate(${r.x}px, ${r.y}px)`, width: `${r.w}px`, height: `${r.h}px` } : { width: `${p.width}px` }}
      onPointerDown={down} onClick={click} onPointerEnter={(e) => { if (e.pointerType !== 'touch') hovered.value = id; }}
      onPointerLeave={() => { if (hovered.value === id) hovered.value = null; }}>
      <div class="bc-clip" inert={form === 'chip'}>
        <div class={`bc-body${p.boxed ? ' boxed' : ''}`} data-measure={p.boxed ? undefined : id}
          style={{ width: `${bodyW}px`, height: bodyH === undefined ? undefined : `${bodyH}px` }}>
          <CardBody bench={p.bench} piece={piece} kind={p.kind} index={p.index} count={p.count} titleMax={p.rules?.title_max_chars ?? 120}
            closed={p.closed} rules={p.rules} derived={p.derived} act={p.act} />
        </div>
      </div>
      {form === 'chip' && <Chip piece={piece} kind={p.kind} k={k} />}
      {p.pinned && form === 'card' && !p.closed && <Pin piece={piece} />}
      {form === 'card' && !p.closed && box && (
        <span class="bc-corner" aria-hidden="true" onPointerDown={(e) => { e.stopPropagation(); press(e, piece, box, p.z, true, () => undefined); }} />
      )}
      {p.lines?.[0] && p.aside && r && (p.aside.kind === 'says'
        ? <Says line={p.lines[0]} k={k} at={{ x: p.aside.box.x - r.x, y: p.aside.box.y - r.y }} />
        : <LinesBadge lines={p.lines} k={k} at={{ x: p.aside.box.x - r.x, y: p.aside.box.y - r.y }} />)}
    </div>
  );
}
