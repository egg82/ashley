// A laid-out screen: the pieces she arranged on a four-column grid by size, each drawn by its kind, animated by piece id
// when the arrangement changes (`rooms/workshop/pieces/flip.ts`). Under reduced motion a change just lands.
import { useLayoutEffect, useRef } from 'preact/hooks';
import { animateLayout, elements, measure, type Box } from '../rooms/workshop/pieces/flip';
import { drawPart, type PartSources } from '../components/parts/registry';
import { reduced } from '../shell/motion';
import type { Layout } from './layout';
import { NARROW, rowsOf, WIDE } from './rows';
import { kioskControls, kioskHome } from './sources';
import { Talk } from './Talk';

const SOURCES: PartSources = { controls: kioskControls, home: kioskHome, conversation: () => <Talk /> };

function signature(layout: Layout): string {
  return layout.placed.map((p) => `${p.id}:${p.kind}:${p.size}`).join(',');
}

function useLayoutMotion(grid: { current: HTMLDivElement | null }, layout: Layout): void {
  const last = useRef<{ boxes: Map<number, Box>; els: Map<number, HTMLElement>; sig: string } | null>(null);
  useLayoutEffect(() => {
    const g = grid.current;
    if (!g) return;
    const sig = signature(layout);
    if (last.current && last.current.sig !== sig && !reduced()) animateLayout(g, last.current, null);
    last.current = { boxes: measure(g), els: elements(g), sig };
  });
}

export function Board({ layout }: { layout: Layout }) {
  const grid = useRef<HTMLDivElement>(null);
  useLayoutMotion(grid, layout);
  return (
    <div class="k-board" ref={grid} style={{ '--rows-wide': rowsOf(layout.placed, WIDE), '--rows-narrow': rowsOf(layout.placed, NARROW) }}>
      {layout.placed.map((p) => (
        <div key={p.id} class={`k-p k-${p.kind}`} data-piece={p.id} data-size={p.size} data-kind={p.kind}>
          {drawPart(p.kind, SOURCES)}
        </div>
      ))}
    </div>
  );
}
