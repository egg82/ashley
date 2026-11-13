// Her reach as a map: the household's hub and the person's, each connection a node on its holder's hub with its age under
// it, a ghost node for each kind that could be added. Pressing a node opens its row; pressing a ghost starts adding it. On a
// phone there is no map, only the summary above it.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { openForm } from '../picking';
import { HUB_R, NODE_R, planOf, type Hub, type MapNode, type MapPlan } from './mapPlan.ts';
import { cutting, opened, openRow } from './state';
import { useWide } from './useWide';

function press(act: () => void) {
  return { onClick: act, onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); } } };
}

function Spoke({ hub, n }: { hub: Hub; n: MapNode }) {
  const mx = (hub.x + n.x) / 2;
  const my = (hub.y + n.y) / 2;
  if (n.needs) {
    return (
      <g class="rm-spoke broken">
        <path d={`M${hub.x} ${hub.y}L${hub.x + (mx - hub.x) * 0.55} ${hub.y + (my - hub.y) * 0.55}`} />
        <path d={`M${n.x} ${n.y}L${n.x + (mx - n.x) * 0.55} ${n.y + (my - n.y) * 0.55}`} />
      </g>
    );
  }
  const cut = n.id !== null && cutting.value === n.id;
  return cut ? (
    <g class="rm-spoke cut">
      <path d={`M${hub.x} ${hub.y}L${mx} ${my}`} class="half a" />
      <path d={`M${n.x} ${n.y}L${mx} ${my}`} class="half b" />
    </g>
  ) : <path class={`rm-spoke${n.ghost ? ' ghost' : ''}${n.band === 'today' ? ' live' : ''}`} d={`M${hub.x} ${hub.y}L${n.x} ${n.y}`} />;
}

function Spark({ hub, n }: { hub: Hub; n: MapNode }) {
  if (n.ghost || n.band !== 'today' || n.needs) return null;
  return <circle class="rm-spark" r="2.6" style={{ offsetPath: `path('M${hub.x} ${hub.y}L${n.x} ${n.y}')` }} />;
}

function Teeth({ n }: { n: MapNode }) {
  if (n.teeth.length < 2) return null;
  return (
    <>
      {n.teeth.map((t, i) => {
        const a = (-90 + (360 * i) / n.teeth.length) * (Math.PI / 180);
        return <circle key={t.ref} class={`rm-tooth${t.shared ? ' shared' : ''}`} r="3.6" cx={Math.cos(a) * (NODE_R + 9)} cy={Math.sin(a) * (NODE_R + 9)} />;
      })}
    </>
  );
}

function label(n: MapNode): string {
  if (n.ghost) return `Add ${n.title}`;
  return `${n.title}, answered ${n.age}${n.needs ? ', needs a person' : ''}. Open`;
}

function Label({ n }: { n: MapNode }) {
  const age = n.ghost ? 'could be added' : n.age;
  if (n.side === 'below') {
    return <><text class="rm-title" y={NODE_R + 15} text-anchor="middle">{n.title}</text><text class="rm-age" y={NODE_R + 28} text-anchor="middle">{age}</text></>;
  }
  const x = n.side === 'left' ? -(NODE_R + 9) : NODE_R + 9;
  const anchor = n.side === 'left' ? 'end' : 'start';
  return <><text class="rm-title" x={x} y="-1" text-anchor={anchor}>{n.title}</text><text class="rm-age" x={x} y="13" text-anchor={anchor}>{age}</text></>;
}

function Node({ n, kinds }: { n: MapNode; kinds: readonly ConnectionKindInfo[] }) {
  const act = () => {
    const kind = kinds.find((k) => k.name === n.kind);
    if (n.id !== null) openRow(n.id);
    else if (kind) openForm(kind, '', false);
  };
  const sel = n.id !== null && opened.value === n.id;
  const cls = `rm-node ${n.hub}${n.ghost ? ' ghost' : ` ${n.band}`}${n.needs ? ' needs' : ''}${sel ? ' sel' : ''}`;
  return (
    <g class={cls} transform={`translate(${n.x} ${n.y})`} role="button" tabindex={0} aria-label={label(n)} {...press(act)}>
      <circle class="rm-ring" r={NODE_R} />
      <text class="rm-mono" y="4" text-anchor="middle">{n.ghost ? '+' : n.title.replace(/[^A-Za-z0-9]/g, '').slice(0, 2)}</text>
      <Teeth n={n} />
      {n.needs && <g class="rm-bang" transform={`translate(${NODE_R * 0.75} ${-NODE_R * 0.75})`}><circle r="8" /><text y="3.8" text-anchor="middle">!</text></g>}
      <Label n={n} />
    </g>
  );
}

function Graph({ plan, kinds }: { plan: MapPlan; kinds: readonly ConnectionKindInfo[] }) {
  return (
    <svg class="rm-svg" viewBox={`0 0 ${plan.w} ${plan.h}`} role="group" aria-label="Where her reach goes">
      {plan.hubs.map((h) => {
        const ring = plan.nodes.filter((n) => n.hub === h.id);
        return <g key={h.id}>{ring.map((n) => <Spoke key={n.key} hub={h} n={n} />)}{ring.map((n) => <Spark key={n.key} hub={h} n={n} />)}</g>;
      })}
      <line class="rm-link" x1={plan.hubs[0]!.x + HUB_R} y1={plan.hubs[0]!.y} x2={plan.hubs[1]!.x - HUB_R} y2={plan.hubs[1]!.y} />
      {plan.hubs.map((h) => (
        <g key={h.id} class={`rm-hub ${h.id}`} transform={`translate(${h.x} ${h.y})`}>
          <circle r={HUB_R} />
          <text class="rm-hub-name" y="4" text-anchor="middle">{h.label}</text>
          <text class="rm-age" y={HUB_R + 16} text-anchor="middle">{h.sub}</text>
        </g>
      ))}
      {plan.nodes.map((n) => <Node key={n.key} n={n} kinds={kinds} />)}
    </svg>
  );
}

const LEGEND: [string, string][] = [['today', 'Answered today'], ['week', 'This week'], ['older', 'Longer ago'], ['needs', 'Needs a person'], ['ghost', 'Could be added']];

export function ReachMap({ connections, kinds, person }: { connections: readonly HouseholdConnection[]; kinds: readonly ConnectionKindInfo[]; person: string }) {
  if (!useWide()) return null;
  const plan = planOf(connections, kinds, Date.now(), person);
  return (
    <section class="rm" aria-label="Her reach">
      <Graph plan={plan} kinds={kinds} />
      <ul class="rm-legend meta">{LEGEND.map(([k, t]) => <li key={k}><i class={`rm-key ${k}`} />{t}</li>)}</ul>
    </section>
  );
}
