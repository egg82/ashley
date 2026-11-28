// The canvas's focus and what follows from it: the bench opens focused on the piece changed last, framed with its
// neighbours; a new focus (a click, or a piece someone asked to see) flies the camera there; pieces added after the
// first layout are marked as landing for a moment, so they fade in at the end of their link.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { lookAt, openingZoom, type Cam, type Inset, type View } from '../model/camera';
import { foldDistance } from '../model/mindmap';
import type { Camera } from './useCamera';
import { CANVAS_INSET } from './Chrome';
import { GOAL_BOX, type Placement } from './usePlacement';
import { focusAsk } from './state';

/** How long a piece just added is marked as landing (its fade, then her brass edge). */
const LANDING_MS = 2000;

export function latest(cards: readonly BenchPiece[]): number | null {
  return cards.reduce<BenchPiece | null>((a, p) => (!a || p.changed_by > a.changed_by ? p : a), null)?.id ?? null;
}

/** The camera at zoom `z` that shows piece `id` with its neighbours and the goal when they fit inside `inset`, else the
 *  neighbours alone. When the bench `opening`, it prefers the goal to the neighbours: the piece and the goal, else the
 *  whole piece leaning toward the goal. */
export function shotOf(id: number, place: Placement, view: View, z: number, opening: boolean, inset: Inset): Cam | null {
  const box = place.boxes.get(id);
  if (!box) return null;
  const hops = foldDistance(id, place.links);
  const near = [...place.boxes].filter(([p]) => (hops.get(p) ?? Infinity) <= 1).map(([, b]) => b);
  return lookAt([[GOAL_BOX, ...near], opening ? [GOAL_BOX, box] : near], box, view, z, inset);
}

/** The camera that shows piece `id` for the bench screen: at the zoom it already has when cards are readable there. */
function shot(id: number, place: Placement, camera: Camera, opening: boolean): Cam | null {
  const z = camera.cam.z >= 1 && !opening ? camera.cam.z : openingZoom(camera.view);
  return shotOf(id, place, camera.view, z, opening, CANVAS_INSET);
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
    const s = shown === null ? null : shot(shown, place, camera, true);
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
    const s = shot(id, place, camera, false);
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
