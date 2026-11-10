// Hold to forget (T10): press and hold, by pointer or by Space/Enter on the focused button, while a ring fills; let go
// early and it drains at four times the speed. The fill is the safety, so it runs under reduced motion too.
import { useEffect, useRef } from 'preact/hooks';

export const HOLD_MS = 1200;
const DRAIN = 4;

interface Props {
  /** 0 to 1, how far the hold has gone; the card paints its own tide from it. */
  onProgress: (p: number) => void;
  /** The ring filled. */
  onDone: () => void;
  disabled: boolean;
}

function useHold({ onProgress, onDone }: Pick<Props, 'onProgress' | 'onDone'>) {
  const s = useRef({ p: 0, p0: 0, t0: 0, holding: false, raf: 0 });
  const cbs = useRef({ onProgress, onDone });
  cbs.current = { onProgress, onDone };

  const step = (now: number) => {
    const h = s.current;
    const dt = now - h.t0;
    h.p = h.holding ? Math.min(1, h.p0 + dt / HOLD_MS) : Math.max(0, h.p0 - (dt * DRAIN) / HOLD_MS);
    cbs.current.onProgress(h.p);
    if (h.holding && h.p >= 1) {
      h.holding = false;
      cbs.current.onDone();
      return;
    }
    if (h.holding || h.p > 0) h.raf = requestAnimationFrame(step);
  };
  const turn = (holding: boolean) => {
    const h = s.current;
    if (h.holding === holding) return;
    cancelAnimationFrame(h.raf);
    Object.assign(h, { holding, t0: performance.now(), p0: h.p });
    h.raf = requestAnimationFrame(step);
  };
  useEffect(() => () => cancelAnimationFrame(s.current.raf), []);
  return { start: () => turn(true), stop: () => turn(false) };
}

const isHoldKey = (e: KeyboardEvent) => e.key === ' ' || e.key === 'Enter';

export function HoldToForget({ onProgress, onDone, disabled }: Props) {
  const { start, stop } = useHold({ onProgress, onDone });
  return (
    <button
      class="btn sm forget"
      type="button"
      disabled={disabled}
      aria-describedby="forget-how"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        start();
      }}
      onPointerUp={stop}
      onPointerCancel={stop}
      onLostPointerCapture={stop}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={(e) => {
        if (!isHoldKey(e)) return;
        e.preventDefault();
        if (!e.repeat) start();
      }}
      onKeyUp={(e) => isHoldKey(e) && stop()}
      onBlur={stop}
    >
      <svg class="ring" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6" pathLength="1" />
        <circle class="fill" cx="8" cy="8" r="6" pathLength="1" />
      </svg>
      <span>Hold to forget</span>
    </button>
  );
}
