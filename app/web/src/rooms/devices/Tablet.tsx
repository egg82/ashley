// The tablet drawn as it will look: each control a button in the order it shows, dragged to reorder or dropped on from the
// house's list. The drag is for a pointer; a tap selects a card and the list's "add" button adds, which is all a phone needs.
import { useState } from 'preact/hooks';
import { added, DOES, MOST, reordered, type Row } from './controlRows';
import type { CatalogueEntityInfo } from '../../api/types';

const SLOTS = 6;
const DRAG = 'application/x-ashley-control';

export type Payload = { from: number } | { entity: string };

export const dragOf = (p: Payload) => (e: DragEvent) => {
  e.dataTransfer?.setData(DRAG, JSON.stringify(p));
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copyMove';
};

function payloadOf(e: DragEvent): Payload | null {
  const raw = e.dataTransfer?.getData(DRAG);
  return raw ? (JSON.parse(raw) as Payload) : null;
}

type Props = {
  rows: Row[];
  place: string;
  name: string;
  picked: number | null;
  lights: CatalogueEntityInfo[];
  onPick: (at: number | null) => void;
  onRows: (rows: Row[]) => void;
};

export function Tablet({ rows, place, name, picked, lights, onPick, onRows }: Props) {
  const [over, setOver] = useState<number | null>(null);
  const drop = (to: number) => (e: DragEvent) => {
    e.preventDefault();
    setOver(null);
    const p = payloadOf(e);
    if (!p) return;
    if ('from' in p) onRows(reordered(rows, p.from, to));
    else onRows(added(rows, lights.find((l) => l.entity_id === p.entity), to));
  };
  const target = (to: number) => ({
    onDragOver: (e: DragEvent) => { e.preventDefault(); setOver(to); },
    onDragLeave: () => setOver((o) => (o === to ? null : o)),
    onDrop: drop(to),
  });
  const empty = Math.max(0, Math.min(SLOTS, MOST) - rows.length);
  return (
    <div class="tb" role="group" aria-label={`${name}'s screen`}>
      <div class="tb-bar"><span>{place}</span><span>{name}</span></div>
      <div class="tb-grid">
        {rows.map((r, i) => (
          <button key={r.name ?? `new-${i}`} class={`tb-card${picked === i ? ' picked' : ''}${over === i ? ' over' : ''}`} type="button" draggable
            aria-pressed={picked === i} onClick={() => onPick(picked === i ? null : i)} onDragStart={dragOf({ from: i })} {...target(i)}>
            <span class="tb-does">{DOES[r.action]}</span>
            <b>{r.label || 'No label'}</b>
            <span class="tb-live">state shows live</span>
          </button>
        ))}
        {Array.from({ length: empty }, (_, k) => (
          <div key={`empty-${k}`} class={`tb-empty${over === rows.length ? ' over' : ''}`} {...target(rows.length)}>drop here</div>
        ))}
      </div>
    </div>
  );
}
