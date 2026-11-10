// Carrying something on screen to a room: while it is carried, the room's bearing (the top bar, or the bottom bar on
// a phone) and its minimap dot light as the drop target, and brighter while the pointer is over either. A drop, or a
// keyboard "send", flies a copy of what was carried into the bearing; under reduced motion the copy only fades.
import { signal } from '@preact/signals';
import { reduced } from './motion';
import type { NavRoomId } from './rooms';

/** The room something being carried may be dropped on, while it is carried. */
export const carryTo = signal<NavRoomId | null>(null);
/** Whether the pointer is over that room's target now. */
export const carryOver = signal(false);

const REACH_PX = 24;
const FLY_MS = 620;
const FADE_MS = 200;
const HELD_SCALE = 0.55;
const LANDED_SCALE = 0.12;
const HANG_PX: readonly [number, number] = [14, 18];

/** The room's bearing link as laid out now (the top bar, or the bottom bar on a phone). */
export function bearingOf(id: NavRoomId): HTMLElement | null {
  return document.querySelector<HTMLElement>(`.bearing a[data-room="${id}"]`);
}

/** Whether (`x`, `y`) is on the room's bearing, with a little reach around it for a finger, or on the minimap. */
export function isOver(id: NavRoomId, x: number, y: number): boolean {
  const within = (r: DOMRect | undefined, pad: number) =>
    !!r && r.width > 0 && x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad;
  return within(bearingOf(id)?.getBoundingClientRect(), REACH_PX) || within(document.querySelector('.minimap')?.getBoundingClientRect(), 0);
}

/** The ghost's untransformed box: left, top, width, height. */
function boxOf(ghost: HTMLElement): [number, number, number, number] {
  const s = ghost.style;
  return [parseFloat(s.left), parseFloat(s.top), parseFloat(s.width), parseFloat(s.height)];
}

/**
 * The transform that hangs `ghost`, shrunk, beside the pointer at (`x`, `y`), on the side away from room `id`'s
 * bearing, so the target stays in sight while it is carried there.
 */
export function heldAt(ghost: HTMLElement, id: NavRoomId, x: number, y: number): string {
  const [left, top, , h] = boxOf(ghost);
  const t = bearingOf(id)?.getBoundingClientRect();
  const above = !!t && t.top + t.height / 2 > y;
  const gy = above ? y - HANG_PX[1] - h * HELD_SCALE : y + HANG_PX[1];
  return `translate(${x + HANG_PX[0] - left}px, ${gy - top}px) scale(${HELD_SCALE}) rotate(-1.5deg)`;
}

/** A copy of `el` laid over it, fixed, for carrying or flying; the caller removes it. */
export function ghostOf(el: HTMLElement): HTMLElement {
  const r = el.getBoundingClientRect();
  const ghost = el.cloneNode(true) as HTMLElement;
  ghost.classList.add('carried');
  ghost.removeAttribute('id');
  Object.assign(ghost.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  document.body.appendChild(ghost);
  return ghost;
}

/**
 * Flies `ghost` from where it sits (`from`, a transform already applied, or none) into room `id`'s bearing on an arc,
 * shrinking and fading as it lands, then removes it. Reduced motion: it fades where it is.
 */
export async function flyInto(ghost: HTMLElement, id: NavRoomId, from = 'none'): Promise<void> {
  const target = bearingOf(id)?.getBoundingClientRect();
  if (reduced() || !target) {
    await ghost.animate([{ transform: from, opacity: 1 }, { transform: from, opacity: 0 }], { duration: FADE_MS, fill: 'forwards' }).finished;
    ghost.remove();
    return;
  }
  const [left, top, w, h] = boxOf(ghost);
  const now = new DOMMatrixReadOnly(from);
  const scale = Math.hypot(now.a, now.b);
  const tx = target.left + target.width / 2 - left - (w * LANDED_SCALE) / 2;
  const ty = target.top + target.height / 2 - top - (h * LANDED_SCALE) / 2;
  const lift = ty < now.f ? -60 : 60;
  const mid = `translate(${now.e + (tx - now.e) * 0.45}px, ${now.f + (ty - now.f) * 0.45 + lift}px) scale(${(scale + LANDED_SCALE) / 2})`;
  await ghost.animate(
    [
      { transform: from, opacity: 1 },
      { offset: 0.45, transform: mid, opacity: 0.9 },
      { transform: `translate(${tx}px, ${ty}px) scale(${LANDED_SCALE})`, opacity: 0 },
    ],
    { duration: FLY_MS, easing: 'cubic-bezier(.65,0,.35,1)', fill: 'forwards' },
  ).finished;
  ghost.remove();
}

const ACK_FADE_MS = 400;

/**
 * A short note by room `id`'s bearing, where a carried thing was just sent: it hangs there for `ms`, then fades. It is
 * not kept anywhere; the room itself shows what became of the thing.
 */
export function acknowledge(id: NavRoomId, text: string, ms: number, failed = false): void {
  const at = bearingOf(id)?.getBoundingClientRect();
  if (!at) return;
  const note = document.createElement('div');
  note.className = failed ? 'ack failed' : 'ack';
  note.setAttribute('role', failed ? 'alert' : 'status');
  note.textContent = text;
  const low = at.top + at.height / 2 > window.innerHeight / 2;
  Object.assign(note.style, {
    right: `${Math.max(8, window.innerWidth - at.right)}px`,
    ...(low ? { bottom: `${window.innerHeight - at.top + 8}px` } : { top: `${at.bottom + 8}px` }),
  });
  document.body.appendChild(note);
  const gone = () => note.remove();
  setTimeout(() => void note.animate([{ opacity: 1 }, { opacity: 0 }], { duration: reduced() ? 0 : ACK_FADE_MS, fill: 'forwards' }).finished.then(gone, gone), ms);
}
