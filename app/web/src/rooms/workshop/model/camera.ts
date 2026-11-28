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
/** Screen px a framing keeps clear on each side of the viewport: a margin, plus whatever the page draws over the canvas
 *  there (its toolbar). */
export interface Inset {
  top: number;
  right: number;
  bottom: number;
  left: number;
}
const MARGIN = 48;
const AROUND: Inset = { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN };

/** The width and height left inside `inset`. */
const room = (v: View, i: Inset) => ({ w: v.w - i.left - i.right, h: v.h - i.top - i.bottom });

/** The camera that draws bench point `c` at the middle of what `inset` leaves, at zoom `z`. */
function centring(c: Pt, v: View, i: Inset, z: number): Cam {
  return { x: c.x - (i.left - i.right) / 2 / z, y: c.y - (i.top - i.bottom) / 2 / z, z };
}

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

/** The camera that shows all of `boxes` inside `inset`, as close as `zCap` and no further out than `zMin`; when they
 *  do not fit at `zMin`, it centres them and the rest is a pan away. */
export function framing(boxes: readonly Box[], v: View, zMin: number, zCap: number, inset: Inset = AROUND): Cam {
  const e = extent(boxes) ?? { x: 0, y: 0, w: 0, h: 0 };
  const r = room(v, inset);
  const z = clampZ(Math.min(r.w / Math.max(1, e.w), r.h / Math.max(1, e.h), zCap), zMin);
  return centring({ x: e.x + e.w / 2, y: e.y + e.h / 2 }, v, inset, z);
}

/** A page `width` wide whose height grows, from `minH` to `maxH`, to show all of `boxes` inside `inset` at zoom 1 or
 *  closer: its view and camera. Null when they do not fit at zoom 1 even at `maxH`. */
export function tallFraming(boxes: readonly Box[], width: number, minH: number, maxH: number, zCap: number, inset: Inset = AROUND): { view: View; cam: Cam } | null {
  const e = extent(boxes) ?? { x: 0, y: 0, w: 0, h: 0 };
  const w = width - inset.left - inset.right;
  const wantH = (z: number) => e.h * z + inset.top + inset.bottom;
  const z = Math.min(zCap, w / Math.max(1, e.w), (maxH - inset.top - inset.bottom) / Math.max(1, e.h));
  if (z < 1) return null;
  const view = { w: width, h: Math.min(maxH, Math.max(minH, Math.ceil(wantH(z)))) };
  return { view, cam: framing(boxes, view, z, z, inset) };
}

/** The camera at zoom `z` centring, inside `inset`, the first of `wants` that fits there: a focus change flies to the
 *  focus with its neighbours (and the goal, when the bench opens). When none fits, it keeps `must` (the focus) inside
 *  and leans as far toward the last of `wants` as that allows. */
export function lookAt(wants: readonly (readonly Box[])[], must: Box, v: View, z: number, inset: Inset = AROUND): Cam {
  const r = room(v, inset);
  const fits = (e: Box) => e.w * z <= r.w && e.h * z <= r.h;
  const boxes = wants.map(extent).filter((e): e is Box => e !== null);
  const c = boxes.find(fits);
  if (c) return centring({ x: c.x + c.w / 2, y: c.y + c.h / 2 }, v, inset, z);
  const toward = boxes.at(-1) ?? must;
  const lean = (from: number, to: number, slack: number) => from + Math.max(-slack, Math.min(slack, to - from));
  const slackX = Math.max(0, (r.w / z - must.w) / 2);
  const slackY = Math.max(0, (r.h / z - must.h) / 2);
  const at = { x: lean(must.x + must.w / 2, toward.x + toward.w / 2, slackX), y: lean(must.y + must.h / 2, toward.y + toward.h / 2, slackY) };
  return centring(at, v, inset, z);
}

/** The part of the bench drawn inside `inset`, in bench units. */
export function visibleBox(cam: Cam, v: View, inset: Inset): Box {
  const tl = toBench(cam, v, { x: inset.left, y: inset.top });
  const r = room(v, inset);
  return { x: tl.x, y: tl.y, w: r.w / cam.z, h: r.h / cam.z };
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
