// The bench drawn as a mindmap: its title at the middle, each piece a card where the layout puts it (`usePlacement.ts`),
// the links between them as lines (`Links.tsx`), under a camera the person pans and zooms (`useCamera.ts`). The focus
// and its neighbours draw in full and the rest fold to chips, and past the zoom where a card's text would drop below
// 12 px everything is a chip (`model/fold.ts`). Dragging a piece pins it (`pinDrag.ts`); her lines sit beside the
// pieces they are about (`HerLines.tsx`).
import { useEffect, useLayoutEffect, useMemo, useRef } from 'preact/hooks';
import type { BenchDetail, WorkshopKinds } from '../../../api/types';
import { redock } from '../../../shell/her/dock';
import { apply, stamps } from '../model/bench';
import { framing, onScreen, openingZoom, worldTransform } from '../model/camera';
import { groupDerived } from '../model/derived';
import { draftsOn } from '../model/drafts';
import { drawnRect, formsOf, minZoom, supersededBy } from '../model/fold';
import { fullIndex, inOrder } from '../model/layout';
import { rootsOf } from '../model/mindmap';
import { cardWidth, placeOf } from '../model/placing';
import { AddPiece, Orphan } from '../pieces/AddPiece';
import { away, herAt, markStamps } from '../pieces/marks';
import type { PieceActions } from '../pieces/PieceCard';
import { CanvasCard } from './CanvasCard';
import { Goal, Legend, Zoom } from './Chrome';
import { useHerLines } from './HerLines';
import { Links } from './Links';
import { dragging, pending } from './state';
import { useCamera } from './useCamera';
import { useFocus } from './useFocus';
import { useMeasure } from './useMeasure';
import { GOAL_BOX, usePlacement } from './usePlacement';

const NONE: readonly never[] = [];

/** Whether a wheel over `t` should scroll what it is over: a full card's content that can scroll that way. */
function scrolls(t: Element): boolean {
  for (let el: Element | null = t; el && !el.classList.contains('bc-card'); el = el.parentElement) {
    if (el.scrollHeight > el.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) return true;
  }
  return false;
}

function useActions(bench: { current: BenchDetail }): PieceActions {
  return useMemo(() => ({
    moveTo(id, to) {
      const b = bench.current;
      const all = inOrder(b.pieces, null).map((p) => p.id);
      const shown = inOrder(groupDerived(b.pieces).cards, null).map((p) => p.id);
      const piece = b.pieces.find((p) => p.id === id);
      if (piece) void apply({ type: 'move', piece_id: id, placement: { order: fullIndex(all, shown, id, to), size: piece.placement.size } });
    },
    remove: (piece) => void apply({ type: 'remove', piece_id: piece.id }),
    archive: (piece) => void apply({ type: 'archive', piece_id: piece.id }),
    grab: () => undefined,
  }), []);
}

interface Props {
  bench: BenchDetail;
  rules: WorkshopKinds | null;
  adding: boolean;
  doneAdding: () => void;
}

export function BenchCanvas({ bench, rules, adding, doneAdding }: Props) {
  const vp = useRef<HTMLDivElement>(null);
  const world = useRef<HTMLDivElement>(null);
  const latest = useRef(bench);
  latest.current = bench;
  const id = bench.bench.id;
  const closed = bench.bench.closed_at !== null;
  const kinds = useMemo(() => new Map(rules?.kinds.map((k) => [k.name, k]) ?? []), [rules]);
  const measured = useMeasure(world);
  const place = usePlacement(bench, kinds, measured);
  const camera = useCamera(vp, minZoom([...place.boxes.values()]), scrolls);
  const { cam, view } = camera;
  const { focus, setFocus, landing } = useFocus(place, camera);
  const ids = new Set(place.boxes.keys());
  const superseded = supersededBy(place.links, ids);
  const forms = formsOf({ ids: [...ids], focus, links: place.links, pinned: place.pinned, superseded, z: cam.z });
  const rects = new Map([...place.boxes].map(([p, b]) => [p, drawnRect(b, forms.get(p)!, cam.z)]));
  const lines = useHerLines(id, place.cardOf, ids);
  const act = useActions(latest);
  const order = inOrder(place.cards, null);
  const seen = (p: number) => !!rects.get(p) && onScreen(cam, view, rects.get(p)!);
  useEffect(() => markStamps(stamps.value, new Set(bench.pieces.map((p) => p.id)), seen), [stamps.value]);
  useEffect(() => { if (away.value && seen(away.value.piece)) away.value = null; }, [cam]);
  useLayoutEffect(() => redock(false), [herAt.value, cam]);
  const orphans = draftsOn(id).filter(([p]) => !bench.pieces.some((x) => x.id === p));
  const whole = () => camera.fly(framing([GOAL_BOX, ...place.boxes.values()], view, 0, openingZoom(view)));
  return (
    <div class="bcanvas">
      <div class={`bc-view${dragging.value ? ' dragging' : ''}`} ref={vp}
        onPointerDown={(e) => !(e.target as Element).closest('.bc-card, .bc-ui') && camera.pan(e)}>
        <div ref={world} class={`bc-world${camera.still || dragging.value ? ' still' : ''}${ids.size || !place.cards.length ? '' : ' unready'}`}
          style={{ transform: worldTransform(cam, view) }}>
          <Links links={place.links} rects={rects} goal={GOAL_BOX} roots={rootsOf(ids, place.links)} landing={landing} z={cam.z}
            full={new Set([...forms].filter(([, f]) => f === 'card').map(([p]) => p))} />
          <Goal title={bench.bench.title} count={place.cards.length} z={cam.z} />
          {order.map((p, i) => (
            <CanvasCard key={p.id} bench={id} piece={p} kind={kinds.get(p.kind)} derived={place.derived.get(p.id) ?? NONE} rules={rules}
              closed={closed} act={act} index={i} count={order.length} box={place.boxes.get(p.id)} width={cardWidth(kinds.get(p.kind))}
              boxed={!!placeOf(p, pending.value.get(p.id)).box} form={forms.get(p.id) ?? 'card'} z={cam.z} focused={p.id === focus} pinned={place.pinned.has(p.id)}
              landing={landing.has(p.id)} lines={lines.byPiece.get(p.id)} fresh={lines.fresh(p.id)} focus={setFocus} />
          ))}
        </div>
      </div>
      <div class="bc-ui bc-side">
        <Legend />
        {orphans.map(([p, d]) => <Orphan key={`o${p}`} bench={id} piece={p} draft={d} />)}
        {adding && rules && <AddPiece bench={id} rules={rules} done={doneAdding} />}
      </div>
      <Zoom step={camera.step} whole={whole} />
      {!place.cards.length && !adding && !orphans.length && (
        <p class="bc-empty meta">{closed ? 'Nothing was left on this bench.' : bench.shelf.length ? 'Nothing out on this bench.' : 'Nothing on this bench yet. Add a piece to start.'}</p>
      )}
    </div>
  );
}
