// The camera flight between rooms (T1). The field flies to the new room; the old room leaves 80px along the travel
// vector; the new room is laid out, her mark is sent to its dock, then it arrives from the far side.
import { signal } from '@preact/signals';
import { reduced } from './motion';
import { room, type RoomId } from './rooms';

const LEAVE_MS = 290;
const LEAVE_REDUCED_MS = 130;
const ENTER_AT_MS = 270;
const ARRIVE_MS = 640;
const CAMERA_MS = 900;
const SLIDE_PX = 80;

/** The room laid out and docked into. */
export const shown = signal<RoomId>('signin');
/** Where the camera points; the field's transform follows it. */
export const camera = signal<RoomId>('signin');
export const leaving = signal<RoomId | null>(null);
export const arriving = signal(false);
/** True from the start of a flight until the camera lands; the field's bearing labels show only then. */
export const flying = signal(false);
/** The travel vector rooms slide along, in px, from the old room toward the new one, negated. */
export const vector = signal<[number, number]>([0, 0]);
/** Bumped by every landing the camera should jump to rather than fly (start, resize). */
export const jump = signal(0);
/** Set when a room was entered and waits for its dock to be measured before it arrives. */
export const entering = signal(false);

let timers: number[] = [];
let flown = false;

function later(ms: number, fn: () => void): void {
  timers.push(window.setTimeout(fn, ms));
}

function travel(from: RoomId, to: RoomId): [number, number] {
  const [ax, ay] = room(from).at;
  const [bx, by] = room(to).at;
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy);
  return len < 1 ? [0, 0] : [(-dx / len) * SLIDE_PX, (-dy / len) * SLIDE_PX];
}

/** Show `to` with no flight: the first room on load. */
export function land(to: RoomId): void {
  shown.value = to;
  camera.value = to;
  jump.value++;
  flown = false;
  entering.value = true;
}

/** Fly from the room shown now to `to`. A flight started mid-flight takes over from wherever things are. */
export function flyTo(to: RoomId): void {
  const from = shown.value;
  if (from === to && camera.value === to) return;
  timers.forEach(clearTimeout);
  timers = [];
  vector.value = travel(from, to);
  camera.value = to;
  leaving.value = from === to ? null : from;
  arriving.value = false;
  flying.value = !reduced();
  later(reduced() ? LEAVE_REDUCED_MS : LEAVE_MS, () => (leaving.value = null));
  later(CAMERA_MS, () => (flying.value = false));
  const enter = () => {
    flown = true;
    shown.value = to;
    entering.value = true;
  };
  if (reduced()) enter();
  else later(ENTER_AT_MS, enter);
}

/** Whether the room being entered was flown to, rather than landed on. */
export function wasFlown(): boolean {
  return flown;
}

/** Called once the entered room is laid out and her mark has been sent to its dock: start the arrival. */
export function arrive(): void {
  entering.value = false;
  if (!flown) return;
  arriving.value = true;
  later(ARRIVE_MS, () => (arriving.value = false));
}
