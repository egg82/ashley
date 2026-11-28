// The bench as a look photographs it: the screen's mindmap (`canvas/`) under a camera fixed where the bench opens, on
// the piece changed last with its neighbours and the goal. Read-only, and no camera moves: the first frame is the one
// taken. A card still waiting to be measured is marked `.measuring` until the layout has every card.
import { useMemo, useRef } from 'preact/hooks';
import type { BenchDetail, WorkshopKinds } from '../../../api/types';
import { framing, openingZoom, tallFraming, worldTransform, type Cam, type Inset, type View } from '../model/camera';
import { drawnRect, formsOf, minZoom, supersededBy } from '../model/fold';
import { rootsOf } from '../model/mindmap';
import { cardWidth } from '../model/placing';
import { inOrder } from '../model/layout';
import type { PieceActions } from '../pieces/PieceCard';
import { CanvasCard } from '../canvas/CanvasCard';
import { Goal } from '../canvas/Chrome';
import { latest, shotOf } from '../canvas/useFocus';
import { Links } from '../canvas/Links';
import { useMeasure } from '../canvas/useMeasure';
import { GOAL_BOX, usePlacement, type Placement } from '../canvas/usePlacement';

const MARGIN: Inset = { top: 32, right: 32, bottom: 32, left: 32 };
const NONE: readonly never[] = [];
const NO_LANDING: ReadonlySet<number> = new Set();
const READ_ONLY: PieceActions = { moveTo: () => undefined, remove: () => undefined, archive: () => undefined, grab: () => undefined };

/** The page is as tall as the shot allows (`max_height` in `looks.json`). */
const MAX_H = 2400;

interface Shot {
  view: View;
  cam: Cam;
  /** The piece in focus (drawn in full with its neighbours, the rest folded); null for the whole bench in full. */
  focus: number | null;
}

/** The whole bench when it fits at a readable zoom on a page grown as tall as it needs; else the piece changed last,
 *  with its neighbours, on a page the size of the window. */
function shotFor(place: Placement): Shot {
  const win: View = { w: innerWidth, h: innerHeight };
  const z = openingZoom(win);
  const whole = tallFraming([GOAL_BOX, ...place.boxes.values()], win.w, win.h, MAX_H, z, MARGIN);
  if (whole) return { ...whole, focus: null };
  const focus = latest(place.cards.filter((p) => place.boxes.has(p.id)));
  const near = focus === null ? null : shotOf(focus, place, win, z, false, MARGIN);
  return { view: win, cam: near ?? framing([GOAL_BOX], win, 0, z, MARGIN), focus };
}

export function LookCanvas({ bench, rules }: { bench: BenchDetail; rules: WorkshopKinds }) {
  const world = useRef<HTMLDivElement>(null);
  const kinds = useMemo(() => new Map(rules.kinds.map((k) => [k.name, k])), [rules]);
  const place = usePlacement(bench, kinds, useMeasure(world));
  const ids = new Set(place.boxes.keys());
  const { view, cam, focus } = shotFor(place);
  const z = Math.max(cam.z, minZoom([...place.boxes.values()]));
  const forms = formsOf({ ids: [...ids], focus, links: place.links, pinned: place.pinned, superseded: supersededBy(place.links, ids), z });
  const rects = new Map([...place.boxes].map(([p, b]) => [p, drawnRect(b, forms.get(p)!, z)]));
  const order = inOrder(place.cards, null);
  return (
    <div class="bcanvas" style={{ height: `${view.h}px` }}>
      <div class="bc-view">
        <div ref={world} class="bc-world still" style={{ transform: worldTransform({ ...cam, z }, view) }}>
          <Links links={place.links} rects={rects} goal={GOAL_BOX} roots={rootsOf(ids, place.links)} landing={NO_LANDING} z={z}
            full={new Set([...forms].filter(([, f]) => f === 'card').map(([p]) => p))} />
          <Goal title={bench.bench.title} count={place.cards.length} z={z} />
          {order.map((p, i) => (
            <CanvasCard key={p.id} bench={bench.bench.id} piece={p} kind={kinds.get(p.kind)} derived={place.derived.get(p.id) ?? NONE} rules={rules}
              closed act={READ_ONLY} index={i} count={order.length} box={place.boxes.get(p.id)} width={cardWidth(kinds.get(p.kind))} boxed={false}
              form={forms.get(p.id) ?? 'card'} z={z} focused={p.id === focus} pinned={false} landing={false} lines={undefined} aside={undefined}
              focus={() => undefined} />
          ))}
        </div>
      </div>
    </div>
  );
}
