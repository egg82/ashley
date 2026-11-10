// Her one body: a single fixed element that springs from dock to dock. A dock is an empty `[data-dock]` spot a room
// lays out; the mark is drawn over it, sized to it. The spring itself is a CSS transition on the mark.
import { reduced } from '../motion';

interface Spot {
  x: number;
  y: number;
  w: number;
}

let body: HTMLElement | null = null;
let scope: Element | null = null;
let placed = '';

export function setBody(el: HTMLElement | null): void {
  body = el;
}

/**
 * Where `el` sits once its room has finished arriving: its rect, less the slide its `.room` is animating through.
 * Without this, a dock measured mid-arrival sends her 80px off to one side.
 */
function spotOf(el: Element | null): Spot | null {
  const r = el?.getBoundingClientRect();
  if (!el || !r || !r.width) return null;
  const roomEl = el.closest('.room');
  const slide = roomEl ? new DOMMatrixReadOnly(getComputedStyle(roomEl).transform) : null;
  return { x: r.left - (slide?.m41 ?? 0), y: r.top - (slide?.m42 ?? 0), w: r.width };
}

function place(s: Spot, snap: boolean): void {
  const key = `${Math.round(s.x)},${Math.round(s.y)},${Math.round(s.w)}`;
  if (!body || key === placed) return;
  placed = key;
  body.classList.toggle('snap', snap || reduced());
  body.style.transform = `translate(${s.x}px, ${s.y}px)`;
  body.style.width = `${s.w}px`;
  body.style.height = `${s.w}px`;
}

/** Send her to the first dock inside `scope` (springing, unless `snap`); the top bar's home dock if none shows. */
export function dockIn(room: Element | null, snap: boolean): void {
  scope = room;
  redock(snap);
}

/** Find her room's dock again and go there, or the away dock while she waits at another room's bearing
 * (`moves.ts`). `snap` for a resize or a scroll; a room whose layout changed (a dock removed, another laid out) lets her
 * spring there. */
export function redock(snap = true): void {
  const s = spotOf(document.querySelector('[data-dock-away]'))
    ?? spotOf(scope?.querySelector('[data-dock]') ?? null) ?? spotOf(document.querySelector('[data-dock-home]'));
  if (s) place(s, snap);
}
