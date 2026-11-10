// A bench opened from its card grows out of it: the card picked is remembered with where it sat, and the bench's
// plate, once laid out, starts at that box and grows to its own (T4 of the design). Reduced motion: it fades in.
import { reduced } from '../../../shell/motion';

const GROW_MS = 620;
const FADE_MS = 160;
const EASE_OUT = 'cubic-bezier(.2,.8,.2,1)';

let picked: { id: number; box: DOMRect } | null = null;

/** The card for bench `id` was picked; its plate grows from `card` when it opens. */
export function pickCard(id: number, card: HTMLElement): void {
  picked = { id, box: card.getBoundingClientRect() };
}

/** Plays the growth onto `plate` when bench `id` was opened from its card; otherwise nothing. */
export function growFromCard(plate: HTMLElement | null, id: number): void {
  const from = picked?.id === id ? picked.box : null;
  picked = null;
  if (!plate || !from) return;
  if (reduced()) {
    plate.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FADE_MS });
    return;
  }
  const to = plate.getBoundingClientRect();
  if (!to.width || !to.height) return;
  const start = `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${from.width / to.width}, ${from.height / to.height})`;
  plate.animate([{ transformOrigin: '0 0', transform: start }, { transformOrigin: '0 0', transform: 'none' }],
    { duration: GROW_MS, easing: EASE_OUT });
  for (const child of Array.from(plate.children)) {
    child.animate([{ opacity: 0 }, { opacity: 0, offset: 0.45 }, { opacity: 1 }], { duration: GROW_MS, easing: EASE_OUT });
  }
}
