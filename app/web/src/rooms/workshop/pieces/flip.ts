// The grid's motion, by piece id, between one layout and the next: a piece that moved glides from where it was (FLIP),
// a new one arrives, a removed one is put back where it stood and leaves. Reduced motion: each only fades.
import { reduced } from '../../../shell/motion';

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const GLIDE_MS = 320;
const ARRIVE_MS = 420;
const LEAVE_MS = 280;
const FADE_MS = 180;
const EASE_OUT = 'cubic-bezier(.2,.8,.2,1)';
const EASE_IN = 'cubic-bezier(.5,0,.9,.4)';

/** Each piece's laid-out box in `grid` (its offset parent), by id. Offsets ignore transforms, so a piece still
 * gliding, or being dragged, is measured where the layout puts it. */
export function measure(grid: HTMLElement): Map<number, Box> {
  const out = new Map<number, Box>();
  grid.querySelectorAll<HTMLElement>(':scope > [data-piece]').forEach((el) => {
    out.set(Number(el.dataset.piece), { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
  });
  return out;
}

/** The pieces' elements in `grid`, by id. */
export function elements(grid: HTMLElement): Map<number, HTMLElement> {
  const out = new Map<number, HTMLElement>();
  grid.querySelectorAll<HTMLElement>(':scope > [data-piece]').forEach((el) => out.set(Number(el.dataset.piece), el));
  return out;
}

function glide(el: HTMLElement, from: Box, to: Box): void {
  const dx = from.x - to.x;
  const dy = from.y - to.y;
  if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
  if (reduced()) {
    el.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: FADE_MS });
    return;
  }
  el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: GLIDE_MS, easing: EASE_OUT });
}

function arrive(el: HTMLElement): void {
  const frames = reduced()
    ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ opacity: 0, transform: 'translateY(14px) scale(.97)' }, { opacity: 1, transform: 'none' }];
  el.animate(frames, { duration: reduced() ? FADE_MS : ARRIVE_MS, easing: EASE_OUT });
}

function leave(grid: HTMLElement, el: HTMLElement, at: Box): void {
  Object.assign(el.style, { position: 'absolute', left: `${at.x}px`, top: `${at.y}px`, width: `${at.w}px`, height: `${at.h}px`,
    margin: '0', pointerEvents: 'none', zIndex: '-1' });
  el.removeAttribute('data-piece');
  el.setAttribute('aria-hidden', 'true');
  grid.appendChild(el);
  const frames = reduced() ? [{ opacity: 1 }, { opacity: 0 }] : [{ opacity: 1 }, { opacity: 0, transform: 'scale(.94)' }];
  const gone = () => el.remove();
  el.animate(frames, { duration: reduced() ? FADE_MS : LEAVE_MS, easing: EASE_IN, fill: 'forwards' }).finished.then(gone, gone);
}

/**
 * Animates `grid` from the layout `before` (boxes and elements as they were) to the one laid out now. `still` is a
 * piece that is not animated (the one being dragged, which follows the pointer).
 */
export function animateLayout(grid: HTMLElement, before: { boxes: Map<number, Box>; els: Map<number, HTMLElement> },
                              still: number | null): void {
  const now = measure(grid);
  const els = elements(grid);
  now.forEach((box, id) => {
    const el = els.get(id)!;
    const was = before.boxes.get(id);
    if (id === still) return;
    if (was) glide(el, was, box);
    else arrive(el);
  });
  before.boxes.forEach((box, id) => {
    const el = before.els.get(id);
    if (!now.has(id) && el && !el.isConnected) leave(grid, el, box);
  });
}
