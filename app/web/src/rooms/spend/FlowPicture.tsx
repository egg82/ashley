// The flow picture: tasks down the left, providers down the right, a cable for each task a provider answered. Cable width
// is cost and the beads running along it are calls. A dashed cable is unpriced, a dotted one reported no usage, and a "?"
// sits on a cable where only some calls are unknown. Reduced motion freezes the beads and stops the halos.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { figureText } from './certainty';
import { layoutOf } from './flowLayout';
import { beadCount, cableKind, cableWidth, flowsOf, samePick, type FlowGraph, type Pick } from './flowModel';
import { taskName } from './routeChoice';
import { motion } from '../../shell/motion';

const clip = (s: string, max: number) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);

function useWidth(): [{ current: HTMLDivElement | null }, number] {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const watch = new ResizeObserver(() => setWidth(el.clientWidth));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  return [box, width];
}

/** Moves each flow's beads along its cable, and the "?" to the middle of it; frozen and evenly spaced when `still`. */
function useBeads(svg: { current: SVGSVGElement | null }, still: boolean, deps: unknown[]): void {
  useEffect(() => {
    const root = svg.current;
    if (!root) return;
    const flows = Array.from(root.querySelectorAll<SVGGElement>('.sp-flow')).map((g) => {
      const path = g.querySelector<SVGPathElement>('.sp-cable')!;
      return { path, len: path.getTotalLength(), beads: Array.from(g.querySelectorAll<SVGCircleElement>('.sp-bead')), pin: g.querySelector<SVGGElement>('.sp-pin') };
    });
    for (const f of flows) {
      if (!f.pin) continue;
      const at = f.path.getPointAtLength(f.len / 2);
      f.pin.setAttribute('transform', `translate(${at.x} ${at.y})`);
    }
    const place = (t: number) => {
      for (const f of flows) {
        f.beads.forEach((b, i) => {
          const along = still ? (i + 0.5) / f.beads.length : (t * (0.05 + 0.012 * f.beads.length) + i / f.beads.length) % 1;
          const at = f.path.getPointAtLength(along * f.len);
          b.setAttribute('cx', String(at.x));
          b.setAttribute('cy', String(at.y));
        });
      }
    };
    place(0);
    if (still) return;
    let frame = requestAnimationFrame(function tick(ms) {
      place(ms / 1000);
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [still, ...deps]);
}

export function FlowPicture({ g, pick, onPick }: { g: FlowGraph; pick: Pick | null; onPick: (p: Pick | null) => void }) {
  const [box, width] = useWidth();
  const svg = useRef<SVGSVGElement>(null);
  const still = motion.value === 'reduced';
  const l = layoutOf(g, Math.max(width, 480));
  useBeads(svg, still, [g, width]);
  const covered = new Set(flowsOf(g, pick).map((f) => f.id));
  const toggle = (p: Pick) => onPick(samePick(pick, p) ? null : p);
  const press = (p: Pick) => (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle(p);
    }
  };
  return (
    <div class="sp-board" ref={box}>
      <svg ref={svg} class={`sp-svg${pick ? ' has-pick' : ''}`} viewBox={`0 0 ${l.width} ${l.height}`} height={l.height} role="group"
        aria-label="Calls from each task to the provider that answered" onKeyDown={(e) => e.key === 'Escape' && onPick(null)}>
        <text class="sp-col" x={0} y={9}>TASKS</text>
        <text class="sp-col" x={l.xProvider + 20} y={9}>PROVIDERS</text>
        {g.flows.map((f) => {
          const kind = cableKind(f.span);
          const w = cableWidth(f.span, g.peak);
          const d = l.path(f.id);
          const p: Pick = { kind: 'flow', id: f.id };
          const name = `${taskName(f.task)} to ${g.providers.find((x) => x.id === f.provider)?.label}, ${figureText(f.span)}`;
          return (
            <g key={f.id} class={`sp-flow ${kind}${covered.has(f.id) ? ' on' : ''}`}>
              {kind === 'measured' || kind === 'partial' ? <path class="sp-glow" d={d} stroke-width={w + 8} /> : null}
              <path class="sp-cable" d={d} stroke-width={w} />
              {Array.from({ length: beadCount(f.totals.calls) }, (_, i) => <circle key={i} class="sp-bead" r={Math.max(2, Math.min(4, w * 0.28))} />)}
              {kind === 'partial' && <g class="sp-pin"><circle r="7" /><text y="3.5">?</text></g>}
              <path class="sp-hit" d={d} tabindex={0} role="button" aria-label={name} aria-pressed={samePick(pick, p)}
                onClick={() => toggle(p)} onKeyDown={press(p)} />
            </g>
          );
        })}
        {g.tasks.map((t) => {
          const p: Pick = { kind: 'task', id: t.id };
          const y = l.taskY.get(t.id)!;
          const room = Math.max(8, Math.floor((l.xTask - 18 - 68) / 7));
          return (
            <g key={t.id} class={`sp-node${samePick(pick, p) ? ' sel' : ''}`} tabindex={0} role="button" aria-pressed={samePick(pick, p)}
              aria-label={`${t.label}, ${figureText(t.span)}`} onClick={() => toggle(p)} onKeyDown={press(p)}>
              <title>{t.label}</title>
              <rect x={-6} y={y - 12.5} width={l.xTask + 20} height={25} fill="transparent" />
              <circle class="sp-halo" cx={l.xTask} cy={y} r={11} />
              <circle class="sp-core" cx={l.xTask} cy={y} r={6} />
              <text class="sp-nm" x={0} y={y + 4}>{clip(t.label, room)}</text>
              <text class={`sp-nc ${t.span.kind}`} x={l.xTask - 18} y={y + 4} text-anchor="end">{figureText(t.span)}</text>
            </g>
          );
        })}
        {g.providers.map((pv) => {
          const p: Pick = { kind: 'provider', id: pv.id };
          const y = l.providerY.get(pv.id)!;
          return (
            <g key={pv.id} class={`sp-node${samePick(pick, p) ? ' sel' : ''}`} tabindex={0} role="button" aria-pressed={samePick(pick, p)}
              aria-label={`${pv.label}, ${figureText(pv.span)}`} onClick={() => toggle(p)} onKeyDown={press(p)}>
              <title>{pv.label}</title>
              <rect x={l.xProvider - 20} y={y - 20} width={l.width - l.xProvider + 20} height={40} fill="transparent" />
              <circle class="sp-halo" cx={l.xProvider} cy={y} r={14} />
              <circle class="sp-core" cx={l.xProvider} cy={y} r={8} />
              <text class="sp-nm" x={l.xProvider + 20} y={y - 2}>{clip(pv.label, 22)}</text>
              <text class={`sp-nc ${pv.span.kind}`} x={l.xProvider + 20} y={y + 13}>{figureText(pv.span)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
