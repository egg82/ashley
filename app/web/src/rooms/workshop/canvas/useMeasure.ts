// Each card's content height, measured at its width: every card's body is drawn (a folded one hidden, still laid out),
// so its size is known whatever its form, and a body that grows or shrinks (a run's output, an image loading, "Show
// all") is measured again. Heights are layout px, unaffected by the camera's scale.
import { useLayoutEffect, useRef, useState } from 'preact/hooks';

const SELECTOR = '[data-measure]';

export function useMeasure(world: { current: HTMLElement | null }): ReadonlyMap<number, number> {
  const [heights, setHeights] = useState<ReadonlyMap<number, number>>(new Map());
  const watch = useRef<ResizeObserver | null>(null);
  const watched = useRef(new Set<Element>());
  useLayoutEffect(() => {
    const read = (els: readonly Element[]) => setHeights((was) => {
      let next: Map<number, number> | null = null;
      for (const el of els) {
        const id = Number((el as HTMLElement).dataset.measure);
        const h = (el as HTMLElement).offsetHeight;
        if (!h || Math.abs((was.get(id) ?? -1) - h) < 0.5) continue;
        next ??= new Map(was);
        next.set(id, h);
      }
      return next ?? was;
    });
    watch.current = new ResizeObserver((entries) => read(entries.map((e) => e.target)));
    return () => {
      watch.current?.disconnect();
      watched.current.clear();
    };
  }, []);
  useLayoutEffect(() => {
    const els = Array.from(world.current?.querySelectorAll(SELECTOR) ?? []);
    for (const el of watched.current) if (!el.isConnected) {
      watch.current?.unobserve(el);
      watched.current.delete(el);
    }
    for (const el of els) if (!watched.current.has(el)) {
      watched.current.add(el);
      watch.current?.observe(el);
    }
  });
  return heights;
}
