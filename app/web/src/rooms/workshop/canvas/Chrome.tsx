// What sits on the canvas around the pieces: the goal (the bench's title) at the middle of the map, the zoom controls,
// and the key to the lines.
import { lift } from '../model/fold';
import { GOAL } from './usePlacement';

/** The goal's title size in px at zoom 1, and the least it draws on screen: it grows in bench units as the camera
 *  pulls back, so the bench's name stays the largest text on the map. */
const GOAL_TEXT_PX = 22;
const GOAL_TEXT_MIN_PX = 16;

export function Goal({ title, count, z }: { title: string; count: number; z: number }) {
  const size = Math.max(GOAL_TEXT_PX, GOAL_TEXT_MIN_PX / z);
  return (
    <div class="bc-goal" style={{ transform: `translate(${-GOAL.w / 2}px, ${-GOAL.h / 2}px)`, width: `${GOAL.w}px`, height: `${GOAL.h}px` }}>
      <b style={{ fontSize: `${size}px` }}>{title}</b>
      <span class="meta" style={{ transform: `scale(${lift(z)})` }}>{count === 1 ? '1 piece' : `${count} pieces`}</span>
    </div>
  );
}

export function Zoom({ step, whole }: { step: (dir: 1 | -1) => void; whole: () => void }) {
  return (
    <div class="bc-ui bc-zoom" role="group" aria-label="Zoom">
      <button class="btn sm" type="button" aria-label="Zoom in" onClick={() => step(1)}>+</button>
      <button class="btn sm" type="button" aria-label="Zoom out" onClick={() => step(-1)}>−</button>
      <button class="btn sm" type="button" onClick={whole}>Whole bench</button>
    </div>
  );
}

export function Legend() {
  return (
    <dl class="bc-ui bc-legend" aria-label="Lines">
      <div><dt><svg width="22" height="6"><path class="part_of" d="M0 3h22" /></svg></dt><dd>part of</dd></div>
      <div><dt><svg width="22" height="6"><path class="depends_on" d="M0 3h22" /></svg></dt><dd>depends on</dd></div>
      <div><dt><svg width="22" height="6"><path class="version_of" d="M0 3h22" /></svg></dt><dd>version of</dd></div>
    </dl>
  );
}
