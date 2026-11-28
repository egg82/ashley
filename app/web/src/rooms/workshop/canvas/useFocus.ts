// The canvas's focus and what follows from it: the bench opens focused on the piece changed last, framed with its
// neighbours; a new focus (a click, or a piece someone asked to see) flies the camera there; pieces added after the
// first layout are marked as landing for a moment, so they fade in at the end of their link.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { lookAt, openingZoom } from '../model/camera';
import { foldDistance, type Box } from '../model/mindmap';
import type { Camera } from './useCamera';
import { GOAL_BOX, type Placement } from './usePlacement';
import { focusAsk } from './state';

/** How long a piece just added is marked as landing (its fade, then her brass edge). */
const LANDING_MS = 2000;

function latest(cards: readonly BenchPiece[]): number | null {
  return cards.reduce<BenchPiece | null>((a, p) => (!a || p.changed_by > a.changed_by ? p : a), null)?.id ?? null;
}

/** The camera that shows piece `id` with its neighbours (and the goal too, when `goal` is given and it fits), at the
 *  zoom it already has when cards are readable there. */
function shot(id: number, place: Placement, camera: Camera, goal: Box | null): Parameters<Camera['fly']>[0] | null {
  const box = place.boxes.get(id);
  if (!box) return null;
  const z = camera.cam.z >= 1 && !goal ? camera.cam.z : openingZoom(camera.view);
  const hops = foldDistance(id, place.links);
  const near = [...place.boxes].filter(([p]) => (hops.get(p) ?? Infinity) <= 1).map(([, b]) => b);
  return lookAt(goal ? [[goal, ...near], near] : [near], box, camera.view, z);
}

export interface Focus {
  focus: number | null;
  setFocus(id: number): void;
  landing: ReadonlySet<number>;
}

export function useFocus(place: Placement, camera: Camera): Focus {
  const [focus, setFocusState] = useState<number | null>(null);
  const [landing, setLanding] = useState<ReadonlySet<number>>(new Set());
  const known = useRef<Set<number> | null>(null);
  const laid = place.boxes.size > 0 && camera.view.w > 0;
  const shown = focus !== null && place.boxes.has(focus) ? focus : latest(place.cards.filter((p) => place.boxes.has(p.id)));
  useLayoutEffect(() => {
    if (!laid || known.current) return;
    known.current = new Set(place.boxes.keys());
    setFocusState(shown);
    const s = shown === null ? null : shot(shown, place, camera, GOAL_BOX);
    if (s) camera.jump(s);
  }, [laid]);
  useEffect(() => {
    if (!known.current) return;
    const fresh = [...place.boxes.keys()].filter((id) => !known.current!.has(id));
    if (!fresh.length) return;
    fresh.forEach((id) => known.current!.add(id));
    setLanding((was) => new Set([...was, ...fresh]));
    setTimeout(() => setLanding((was) => new Set([...was].filter((id) => !fresh.includes(id)))), LANDING_MS);
  }, [place.boxes]);
  const setFocus = (id: number) => {
    if (id === shown && camera.cam.z >= 1) return;
    setFocusState(id);
    const s = shot(id, place, camera, null);
    if (s) camera.fly(s);
  };
  const asked = focusAsk.value;
  useEffect(() => {
    if (asked === null) return;
    focusAsk.value = null;
    setFocus(asked);
  }, [asked]);
  return { focus: shown, setFocus, landing };
}
