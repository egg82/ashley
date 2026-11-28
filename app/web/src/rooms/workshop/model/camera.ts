// The bench canvas's camera: which bench point sits at the middle of the viewport, and how many screen px one bench unit
// draws. Pure. Bench units are the mindmap's (`mindmap.ts`), the goal centred at the origin.
import type { Box, Pt } from './mindmap.ts';

export interface Cam {
  /** The bench point drawn at the middle of the viewport. */
  x: number;
  y: number;
  /** Screen px per bench unit. */
  z: number;
}
export interface View {
  w: number;
  h: number;
}

/** The closest the camera goes. */
export const Z_MAX = 2.4;
/** Each wheel notch or zoom button press. */
export const Z_STEP = 1.2;
/** The space kept around what a framing shows, in screen px. */
const MARGIN = 48;

const clampZ = (z: number, zMin: number): number => Math.min(Z_MAX, Math.max(zMin, z));

/** The zoom a bench opens at: 1 on a laptop, more on a big screen (a garage bench screen reads from further away), so
 *  the type grows with the screen; never below 1, where a card's text is drawn at its own size. */
export function openingZoom(v: View): number {
  return Math.min(1.5, Math.max(1, Math.min(v.w / 1100, v.h / 700)));
}

/** The bench point under screen point `s` (px from the viewport's top-left). */
export function toBench(cam: Cam, v: View, s: Pt): Pt {
  return { x: (s.x - v.w / 2) / cam.z + cam.x, y: (s.y - v.h / 2) / cam.z + cam.y };
}

/** The camera zoomed by `factor` about screen point `s`, which keeps the bench point under it; zoom held to
 *  [`zMin`, `Z_MAX`]. */
export function zoomAt(cam: Cam, factor: number, s: Pt, v: View, zMin: number): Cam {
  const z = clampZ(cam.z * factor, zMin);
  const before = toBench(cam, v, s);
  const moved = { ...cam, z };
  const after = toBench(moved, v, s);
  return { x: cam.x + before.x - after.x, y: cam.y + before.y - after.y, z };
}

/** The camera moved by a drag of `d` screen px. */
export function panBy(cam: Cam, d: Pt): Cam {
  return { ...cam, x: cam.x - d.x / cam.z, y: cam.y - d.y / cam.z };
}

/** The union of `boxes`; null for none. */
export function extent(boxes: readonly Box[]): Box | null {
  if (!boxes.length) return null;
  const x = Math.min(...boxes.map((b) => b.x));
  const y = Math.min(...boxes.map((b) => b.y));
  const r = Math.max(...boxes.map((b) => b.x + b.w));
  const btm = Math.max(...boxes.map((b) => b.y + b.h));
  return { x, y, w: r - x, h: btm - y };
}

/** The camera that shows all of `boxes` with a margin, as close as `zCap` and no further out than `zMin`; when they do
 *  not fit at `zMin`, it centres them and the rest is a pan away. */
export function framing(boxes: readonly Box[], v: View, zMin: number, zCap: number): Cam {
  const e = extent(boxes) ?? { x: 0, y: 0, w: 0, h: 0 };
  const fit = Math.min((v.w - 2 * MARGIN) / Math.max(1, e.w), (v.h - 2 * MARGIN) / Math.max(1, e.h));
  return { x: e.x + e.w / 2, y: e.y + e.h / 2, z: clampZ(Math.min(fit, zCap), zMin) };
}

/** The camera at zoom `z` centred on the first of `wants` that fits on screen at `z`: a focus change flies to the focus
 *  with its neighbours (and the goal, when the bench opens). When none fits, it keeps `must` (the focus) on screen and
 *  leans as far toward the last of `wants` as that allows. */
export function lookAt(wants: readonly (readonly Box[])[], must: Box, v: View, z: number): Cam {
  const fits = (e: Box) => e.w * z <= v.w - 2 * MARGIN && e.h * z <= v.h - 2 * MARGIN;
  const boxes = wants.map(extent).filter((e): e is Box => e !== null);
  const c = boxes.find(fits);
  if (c) return { x: c.x + c.w / 2, y: c.y + c.h / 2, z };
  const toward = boxes.at(-1) ?? must;
  const lean = (from: number, to: number, room: number) => from + Math.max(-room, Math.min(room, to - from));
  const roomX = Math.max(0, ((v.w - 2 * MARGIN) / z - must.w) / 2);
  const roomY = Math.max(0, ((v.h - 2 * MARGIN) / z - must.h) / 2);
  return { x: lean(must.x + must.w / 2, toward.x + toward.w / 2, roomX), y: lean(must.y + must.h / 2, toward.y + toward.h / 2, roomY), z };
}

/** Whether `box` is drawn inside the viewport (its top `edge` bench units at least). */
export function onScreen(cam: Cam, v: View, box: Box, edge = 40): boolean {
  const left = (box.x - cam.x) * cam.z + v.w / 2;
  const top = (box.y - cam.y) * cam.z + v.h / 2;
  return left + box.w * cam.z > 0 && left < v.w && top >= -4 && top + edge * cam.z <= v.h;
}

/** The CSS transform that draws the bench through `cam`, for an element whose origin is its top-left. */
export function worldTransform(cam: Cam, v: View): string {
  return `translate(${v.w / 2 - cam.x * cam.z}px, ${v.h / 2 - cam.y * cam.z}px) scale(${cam.z})`;
}
