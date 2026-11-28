// The canvas's camera as the person moves it: drag the background to pan, the wheel (or a pinch) to zoom about the
// pointer, the buttons to zoom about the middle. A camera set by the page (a focus, "whole bench") glides there (the
// world's transition, `canvas.css`); while the person pans or zooms it follows at once (`still`).
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { panBy, zoomAt, Z_STEP, type Cam, type View } from '../model/camera';

const WHEEL_STEP = 1.1;
const SETTLE_MS = 160;

export interface Camera {
  view: View;
  cam: Cam;
  /** True while the person pans or zooms: the camera follows without gliding. */
  still: boolean;
  /** Glides to `next`. */
  fly(next: Cam): void;
  /** Goes to `next` at once. */
  jump(next: Cam): void;
  /** Zooms about the viewport's middle by one step, in (1) or out (-1). */
  step(dir: 1 | -1): void;
  pan(e: PointerEvent): void;
}

function useView(vp: { current: HTMLElement | null }): View {
  const [view, setView] = useState<View>({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = vp.current;
    if (!el) return;
    const read = () => setView((v) => (v.w === el.clientWidth && v.h === el.clientHeight ? v : { w: el.clientWidth, h: el.clientHeight }));
    read();
    const watch = new ResizeObserver(read);
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  return view;
}

/** `scrolls(target)` says whether a wheel over `target` is the content's to scroll rather than the camera's. */
export function useCamera(vp: { current: HTMLElement | null }, zMin: number, scrolls: (t: Element) => boolean): Camera {
  const view = useView(vp);
  const [cam, setCam] = useState<Cam>({ x: 0, y: 0, z: 1 });
  const [still, setStill] = useState(false);
  const now = useRef({ cam, view, zMin });
  now.current = { cam, view, zMin };
  const settle = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    const el = vp.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      if (!e.ctrlKey && e.target instanceof Element && scrolls(e.target)) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const { cam: c, view: v, zMin: floor } = now.current;
      const factor = e.ctrlKey ? Math.exp(-e.deltaY / 100) : e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP;
      setStill(true);
      setCam(zoomAt(c, factor, { x: e.clientX - r.left, y: e.clientY - r.top }, v, floor));
      clearTimeout(settle.current);
      settle.current = setTimeout(() => setStill(false), SETTLE_MS);
    };
    el.addEventListener('wheel', wheel, { passive: false });
    return () => el.removeEventListener('wheel', wheel);
  }, []);
  useEffect(() => {
    if (cam.z < zMin) setCam((c) => ({ ...c, z: zMin }));
  }, [zMin]);
  const pan = (e: PointerEvent) => {
    const el = e.currentTarget as HTMLElement;
    if (e.button !== 0) return;
    el.setPointerCapture(e.pointerId);
    let last = { x: e.clientX, y: e.clientY };
    setStill(true);
    const move = (ev: PointerEvent) => {
      const d = { x: ev.clientX - last.x, y: ev.clientY - last.y };
      last = { x: ev.clientX, y: ev.clientY };
      setCam((c) => panBy(c, d));
    };
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      setStill(false);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  };
  return {
    view, cam, still, pan,
    fly: (next) => { setStill(false); setCam({ ...next, z: Math.max(now.current.zMin, next.z) }); },
    jump: (next) => {
      setStill(true);
      setCam({ ...next, z: Math.max(now.current.zMin, next.z) });
      requestAnimationFrame(() => requestAnimationFrame(() => setStill(false)));
    },
    step: (dir) => setCam((c) => zoomAt(c, dir > 0 ? Z_STEP : 1 / Z_STEP, { x: view.w / 2, y: view.h / 2 }, view, zMin)),
  };
}
