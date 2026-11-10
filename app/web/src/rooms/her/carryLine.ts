// Picking a line up and carrying it to Memory, with a mouse or a finger. A press held still for a moment lifts the
// line; moving first is an ordinary scroll or text selection, so neither is taken over. Once lifted, a copy follows
// the pointer, the Memory bearing lights (`shell/carry.ts`), and letting go over it remembers the line while the copy
// flies in; letting go anywhere else springs it back.
import { useEffect } from 'preact/hooks';
import type { RefObject } from 'preact';
import { carryOver, carryTo, flyInto, ghostOf, heldAt, isOver } from '../../shell/carry';
import { reduced } from '../../shell/motion';

const HOLD_MS = 280;
const SLOP_PX = 6;
const BACK_MS = 320;

/** Lets the line at `ref` be carried to Memory while `enabled`; `drop` runs as it is let go over the target. */
export function useCarryLine(ref: RefObject<HTMLElement>, enabled: boolean, drop: () => void): void {
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    let carrying = false;
    const stopScroll = (e: TouchEvent) => carrying && e.preventDefault();
    const stopMenu = (e: Event) => carrying && e.preventDefault();
    const down = (e: PointerEvent) => {
      if (e.button !== 0 || (e.target as Element).closest('button, a')) return;
      press(el, e, (on) => (carrying = on), drop);
    };
    el.addEventListener('pointerdown', down);
    // Not passive, so a lifted line's finger moves the copy instead of scrolling the thread.
    el.addEventListener('touchmove', stopScroll, { passive: false });
    el.addEventListener('contextmenu', stopMenu);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('touchmove', stopScroll);
      el.removeEventListener('contextmenu', stopMenu);
    };
  }, [ref, enabled, drop]);
}

/** A press on `el`: lifts it after `HOLD_MS` held within `SLOP_PX`, then carries it until let go. */
function press(el: HTMLElement, e: PointerEvent, carrying: (on: boolean) => void, drop: () => void): void {
  const x0 = e.clientX;
  const y0 = e.clientY;
  const id = e.pointerId;
  const early = (ev: PointerEvent) => ev.pointerId === id && Math.hypot(ev.clientX - x0, ev.clientY - y0) > SLOP_PX && quit();
  const quit = () => {
    clearTimeout(timer);
    removeEventListener('pointermove', early);
    removeEventListener('pointerup', quit);
    removeEventListener('pointercancel', quit);
  };
  const timer = setTimeout(() => {
    quit();
    carrying(true);
    lift(el, id, x0, y0, () => carrying(false), drop);
  }, HOLD_MS);
  addEventListener('pointermove', early);
  addEventListener('pointerup', quit);
  addEventListener('pointercancel', quit);
}

function lift(el: HTMLElement, id: number, x: number, y: number, done: () => void, drop: () => void): void {
  getSelection()?.removeAllRanges();
  const ghost = ghostOf(el);
  el.classList.add('lifted');
  document.documentElement.classList.add('carrying');
  carryTo.value = 'memory';
  let at = heldAt(ghost, 'memory', x, y);
  ghost.style.transform = at;
  const move = (ev: PointerEvent) => {
    if (ev.pointerId !== id) return;
    at = heldAt(ghost, 'memory', ev.clientX, ev.clientY);
    ghost.style.transform = at;
    carryOver.value = isOver('memory', ev.clientX, ev.clientY);
  };
  const end = (ev: PointerEvent) => {
    if (ev.pointerId !== id) return;
    removeEventListener('pointermove', move);
    removeEventListener('pointerup', end);
    removeEventListener('pointercancel', end);
    const hit = ev.type === 'pointerup' && carryOver.value;
    carryTo.value = null;
    carryOver.value = false;
    document.documentElement.classList.remove('carrying');
    done();
    void settle(el, ghost, at, hit, drop);
  };
  addEventListener('pointermove', move);
  addEventListener('pointerup', end);
  addEventListener('pointercancel', end);
}

async function settle(el: HTMLElement, ghost: HTMLElement, at: string, hit: boolean, drop: () => void): Promise<void> {
  if (hit) {
    drop();
    el.classList.remove('lifted');
    await flyInto(ghost, 'memory', at);
    return;
  }
  if (!reduced() && at !== 'none') {
    await ghost.animate([{ transform: at }, { transform: 'none' }], { duration: BACK_MS, easing: 'cubic-bezier(.34,1.45,.64,1)', fill: 'forwards' }).finished;
  }
  ghost.remove();
  el.classList.remove('lifted');
}
