// The canvas's focus and what follows from it: the bench opens focused on the piece changed last, framed with its
// neighbours; a new focus (a click, or a piece someone asked to see) flies the camera there; pieces added after the
// first layout are marked as landing for a moment, so they fade in at the end of their link.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { lookAt, openingZoom } from '../model/camera';
import { shotWants } from '../model/fold';
import { foldDistance } from '../model/mindmap';
import type { Camera } from './useCamera';
import { CANVAS_INSET } from './Chrome';
import { GOAL_BOX, type Placement } from './usePlacement';
import { focusAsk } from './state';

/** How long a piece just added is marked as landing (its fade, then her brass edge). */
const LANDING_MS = 2000;

function latest(cards: readonly BenchPiece[]): number | null {
  return cards.reduce<BenchPiece | null>((a, p) => (!a || p.changed_by > a.changed_by ? p : a), null)?.id ?? null;
}

/** The camera that shows piece `id` with its neighbours and the goal when they fit, clear of the toolbar, at the zoom it
 *  already has when cards are readable there; else the neighbours alone. When the bench `opening`, it prefers the goal
 *  to the neighbours: the piece and the goal, else the whole piece leaning toward the goal. */
function shot(id: number, place: Placement, camera: Camera, why: 'open' | 'turn' | 'person', kept: ReadonlySet<number>): Parameters<Camera['fly']>[0] | null {
  const box = place.boxes.get(id);
  if (!box) return null;
  const opening = why === 'open';
  const z = camera.cam.z >= 1 && !opening ? camera.cam.z : openingZoom(camera.view);
  const hops = foldDistance(id, place.links);
  const near = [...place.boxes].filter(([p]) => (hops.get(p) ?? Infinity) <= 1).map(([, b]) => b);
  const rank = (p: number) => place.cards.find((c) => c.id === p)?.changed_by ?? 0;
  const wants = shotWants(why, { kept, links: place.links, boxes: place.boxes, rank, goal: GOAL_BOX, focus: box, near });
  return lookAt(wants, box, camera.view, z, CANVAS_INSET);
}

export interface Focus {
  focus: number | null;
  setFocus(id: number): void;
  landing: ReadonlySet<number>;
}

export function useFocus(place: Placement, camera: Camera, kept: ReadonlySet<number>): Focus {
  const [focus, setFocusState] = useState<number | null>(null);
  const [landing, setLanding] = useState<ReadonlySet<number>>(new Set());
  const known = useRef<Set<number> | null>(null);
  const laid = place.boxes.size > 0 && camera.view.w > 0;
  const shown = focus !== null && place.boxes.has(focus) ? focus : latest(place.cards.filter((p) => place.boxes.has(p.id)));
  useLayoutEffect(() => {
    if (!laid || known.current) return;
    known.current = new Set(place.boxes.keys());
    setFocusState(shown);
    const s = shown === null ? null : shot(shown, place, camera, 'open', kept);
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
    const s = shot(id, place, camera, 'person', kept);
    if (s) camera.fly(s);
  };
  const keptKey = [...kept].sort().join();
  const keptWas = useRef(keptKey);
  useEffect(() => {
    if (keptKey === keptWas.current) return;
    keptWas.current = keptKey;
    const s = known.current && kept.size && shown !== null ? shot(shown, place, camera, 'turn', kept) : null;
    if (s) camera.fly(s);
  }, [keptKey]);
  const asked = focusAsk.value;
  useEffect(() => {
    if (asked === null) return;
    focusAsk.value = null;
    setFocus(asked);
  }, [asked]);
  return { focus: shown, setFocus, landing };
}
