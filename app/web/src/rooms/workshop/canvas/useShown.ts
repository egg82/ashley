// The canvas following her `bench_show`: what she asked to see or put away is held until the person focuses a piece of
// their own, and the camera frames the pieces unless the person pans or zooms later (the camera is theirs again then).
import { useEffect, useRef, useState } from 'preact/hooks';
import { onBenchShown } from '../../../session/live';
import { framing, openingZoom } from '../model/camera';
import { CANVAS_INSET } from './Chrome';
import { show, NOTHING_HELD, type Held } from './shown';
import type { Camera } from './useCamera';
import { GOAL_BOX, type Placement } from './usePlacement';

export function useShown(bench: number, place: Placement, camera: Camera, focus: number | null): Held {
  const [held, setHeld] = useState<Held>(NOTHING_HELD);
  const now = useRef({ place, camera });
  now.current = { place, camera };
  useEffect(() => setHeld(NOTHING_HELD), [focus]);
  useEffect(() => onBenchShown((at, ids, fold) => {
    if (at !== bench) return;
    const { place: p, camera: c } = now.current;
    show(ids, fold, new Set(p.boxes.keys()), {
      hold: setHeld,
      frame(which) {
        const boxes = which === 'whole' ? [GOAL_BOX, ...p.boxes.values()] : which.map((id) => p.boxes.get(id)!);
        c.fly(framing(boxes, c.view, which === 'whole' ? 0 : 1, openingZoom(c.view), CANVAS_INSET));
      },
    });
  }), [bench]);
  return held;
}
