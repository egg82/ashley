// The lines between pieces, in bench units under the camera: a curve from edge to edge of the two drawn rects, styled
// by kind (part of solid, depends on dashed, version of in the model hue), named at its middle when both ends are full
// cards. A faint spoke runs from the goal to each piece the layout placed around it (`rootsOf`). The stroke stays one
// width on screen at any zoom; a line follows a piece being dragged.
import type { Box, MapLink } from '../model/mindmap';
import { lift } from '../model/fold';
import { dragging } from './state';

const LABEL: Record<MapLink['kind'], string> = { part_of: 'part of', depends_on: 'depends on', version_of: 'version of' };

const mid = (b: Box) => ({ x: b.x + b.w / 2, y: b.y + b.h / 2 });

/** A curve from `a` to `b`, leaving and entering by the sides that face each other, and its middle. */
export function curve(a: Box, b: Box): { d: string; at: { x: number; y: number } } {
  const ca = mid(a);
  const cb = mid(b);
  if (Math.abs(ca.x - cb.x) > (a.w + b.w) / 2) {
    const right = ca.x < cb.x;
    const x1 = right ? a.x + a.w : a.x;
    const x2 = right ? b.x : b.x + b.w;
    const m = (x1 + x2) / 2;
    return { d: `M${x1} ${ca.y} C${m} ${ca.y} ${m} ${cb.y} ${x2} ${cb.y}`, at: { x: m, y: (ca.y + cb.y) / 2 } };
  }
  const down = ca.y < cb.y;
  const y1 = down ? a.y + a.h : a.y;
  const y2 = down ? b.y : b.y + b.h;
  const m = (y1 + y2) / 2;
  return { d: `M${ca.x} ${y1} C${ca.x} ${m} ${cb.x} ${m} ${cb.x} ${y2}`, at: { x: (ca.x + cb.x) / 2, y: m } };
}

interface Props {
  links: readonly MapLink[];
  /** Each laid-out card's drawn rect. */
  rects: ReadonlyMap<number, Box>;
  full: ReadonlySet<number>;
  goal: Box;
  roots: ReadonlySet<number>;
  /** Pieces just added, whose lines draw in after them. */
  landing: ReadonlySet<number>;
  z: number;
}

export function Links({ links, rects, full, goal, roots, landing, z }: Props) {
  const drag = dragging.value;
  const rectOf = (id: number): Box | undefined => {
    const r = rects.get(id);
    if (!r || drag?.id !== id) return r;
    return { x: r.x + drag.dx, y: r.y + drag.dy, w: r.w + drag.dw, h: r.h + drag.dh };
  };
  const k = lift(z);
  return (
    <svg class={`bc-links${drag ? ' live' : ''}`} width="1" height="1" aria-hidden="true">
      {[...roots].map((id) => {
        const r = rectOf(id);
        return r && <path key={`g${id}`} class="spoke" d={curve(goal, r).d} />;
      })}
      {links.map((l) => {
        const a = rectOf(l.from);
        const b = rectOf(l.to);
        if (!a || !b) return null;
        const c = curve(a, b);
        const fresh = landing.has(l.from) || landing.has(l.to);
        return (
          <g key={`${l.from}:${l.kind}:${l.to}`} class={`${l.kind}${fresh ? ' fresh' : ''}`}>
            <path d={c.d} />
            {full.has(l.from) && full.has(l.to) && (
              <text x={c.at.x} y={c.at.y} dx={4 * k} dy={-4 * k} style={{ fontSize: `${10 * k}px` }}>{LABEL[l.kind]}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
