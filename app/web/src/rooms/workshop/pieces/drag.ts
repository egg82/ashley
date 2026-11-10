// Reordering by hand: a piece is carried by its grip and follows the pointer, the others make room as it passes over
// them (the grid shows `preview`, and its FLIP glides them), and letting go settles it on a spring into the order it
// was dropped at. The keyboard way is the grip's arrow keys (`PieceCard`).
import { signal } from '@preact/signals';
import { reduced } from '../../../shell/motion';
import { movedTo } from '../model/layout';

/** The order shown while a piece is carried, or until its move has been read back; null shows the bench's own. */
export const preview = signal<readonly number[] | null>(null);
/** The piece being carried. */
export const carried = signal<number | null>(null);

const SETTLE_MS = 420;
const SPRING = 'cubic-bezier(.34,1.45,.64,1)';

function under(grid: HTMLElement, id: number, x: number, y: number): number | null {
  for (const el of Array.from(grid.querySelectorAll<HTMLElement>(':scope > [data-piece]'))) {
    if (Number(el.dataset.piece) === id) continue;
    const r = el.getBoundingClientRect();
    if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return Number(el.dataset.piece);
  }
  return null;
}

function settle(el: HTMLElement): void {
  const from = el.style.transform;
  el.style.transform = '';
  el.classList.remove('dragging');
  if (!reduced() && from) el.animate([{ transform: from }, { transform: 'none' }], { duration: SETTLE_MS, easing: SPRING });
}

/**
 * Starts carrying piece `id` from a press on its grip. `ids` is the order as shown; `drop` is called with the index
 * it was let go at, when that differs, and the preview is held until `drop` settles.
 */
export function carry(e: PointerEvent, id: number, grid: HTMLElement, ids: readonly number[],
                      drop: (id: number, to: number) => Promise<unknown>): void {
  const el = grid.querySelector<HTMLElement>(`:scope > [data-piece="${id}"]`);
  const grip = e.currentTarget as HTMLElement | null;
  if (!el || !grip || e.button !== 0) return;
  e.preventDefault();
  grip.setPointerCapture(e.pointerId);
  const start = { x: e.clientX - el.offsetLeft, y: e.clientY - el.offsetTop };
  let order = [...ids];
  carried.value = id;
  preview.value = order;
  el.classList.add('dragging');
  const move = (ev: PointerEvent) => {
    el.style.transform = `translate(${ev.clientX - start.x - el.offsetLeft}px, ${ev.clientY - start.y - el.offsetTop}px)`;
    const over = under(grid, id, ev.clientX, ev.clientY);
    if (over === null) return;
    const next = movedTo(order, id, order.indexOf(over));
    if (next.join() !== order.join()) preview.value = order = next;
  };
  const up = () => {
    grip.removeEventListener('pointermove', move);
    grip.removeEventListener('pointerup', up);
    grip.removeEventListener('pointercancel', up);
    carried.value = null;
    settle(el);
    const to = order.indexOf(id);
    if (to === ids.indexOf(id)) preview.value = null;
    else void drop(id, to).finally(() => (preview.value = null));
  };
  grip.addEventListener('pointermove', move);
  grip.addEventListener('pointerup', up);
  grip.addEventListener('pointercancel', up);
}
