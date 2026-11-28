// Dragging a piece on the canvas: by its header it follows the pointer 1:1 and, let go, is pinned where it was dropped;
// by its corner it is resized, which gives it a box and pins it. Either is one move to the server, shown at once and
// put back if the server refuses it (the refusal shows the way any other does, `pieces/why.ts`). A press that does not
// move is a click.
import { batch } from '@preact/signals';
import type { BenchPiece } from '../../../api/types';
import { apply } from '../model/bench';
import type { Box } from '../model/mindmap';
import { heldBox, wholePt, type Pending } from '../model/placing';
import { dragging, pending, setPending } from './state';

/** How far a press moves, in screen px, before it is a drag rather than a click. */
const SLOP = 3;

/** Sends a move that sets `p` on `piece`, showing it until the server has answered (and the bench has been read back). */
export function sendPlace(piece: BenchPiece, p: Pending): void {
  setPending(piece.id, p);
  const placement = { order: piece.placement.order, ...(p.pin !== undefined && { pin: p.pin }), ...(p.box !== undefined && { box: p.box }) };
  void apply({ type: 'move', piece_id: piece.id, placement }).finally(() => {
    if (pending.value.get(piece.id) === p) setPending(piece.id, null);
  });
}

/** The click a drag's release fires is not a click on the piece. */
function swallowClick(): void {
  const stop = (e: Event) => e.stopPropagation();
  window.addEventListener('click', stop, { capture: true, once: true });
  setTimeout(() => window.removeEventListener('click', stop, { capture: true }), 0);
}

/** Follows a press on piece `piece`'s header (`resize` false) or corner (`resize` true), drawn in `box` at zoom `z`. */
export function press(e: PointerEvent, piece: BenchPiece, box: Box, z: number, resize: boolean, click: () => void): void {
  const el = e.currentTarget as HTMLElement;
  if (e.button !== 0) return;
  el.setPointerCapture(e.pointerId);
  const start = { x: e.clientX, y: e.clientY };
  let moved = false;
  const move = (ev: PointerEvent) => {
    const d = { x: (ev.clientX - start.x) / z, y: (ev.clientY - start.y) / z };
    if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < SLOP) return;
    moved = true;
    dragging.value = resize ? { id: piece.id, dx: 0, dy: 0, dw: d.x, dh: d.y } : { id: piece.id, dx: d.x, dy: d.y, dw: 0, dh: 0 };
  };
  const up = () => {
    el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerup', up);
    el.removeEventListener('pointercancel', up);
    const d = dragging.value;
    batch(() => {
      dragging.value = null;
      if (!moved || !d) return;
      const pin = wholePt({ x: box.x + d.dx, y: box.y + d.dy });
      sendPlace(piece, resize ? { pin, box: heldBox(box.w + d.dw, box.h + d.dh) } : { pin });
    });
    if (!moved) click();
    else swallowClick();
  };
  el.addEventListener('pointermove', move);
  el.addEventListener('pointerup', up);
  el.addEventListener('pointercancel', up);
}
