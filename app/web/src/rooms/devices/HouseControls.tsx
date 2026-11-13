// The house's lights and scenes a control can be made for: drag one onto the tablet, or tap add.
import { added, MOST, pickName, type Row } from './controlRows';
import { lights } from './controls';
import { dragOf } from './Tablet';

export function HouseControls({ rows, onRows }: { rows: Row[]; onRows: (rows: Row[]) => void }) {
  const state = lights.value;
  if (state.state === 'loading') return <p class="meta">Reading the house's lights and scenes…</p>;
  if (state.state === 'none') return <p class="meta">Connect Home Assistant to pick lights and scenes for this screen.</p>;
  if (state.state === 'failed') return <span class="unk">Couldn't read the house's lights and scenes</span>;
  if (state.lights.length === 0) return <p class="meta">The house has no lights or scenes to pick from.</p>;
  const full = rows.length >= MOST;
  return (
    <ul class="hc">
      {state.lights.map((l) => {
        const on = rows.some((r) => r.entity_id === l.entity_id);
        return (
          <li key={l.entity_id} class={`hc-item${on ? ' on' : ''}`} draggable={!on && !full} onDragStart={dragOf({ entity: l.entity_id })}>
            <span class="hc-name"><b>{pickName(l)}</b><span class="meta">{l.entity_id}</span></span>
            <button class="btn sm ghost" type="button" disabled={on || full} aria-label={`Add ${l.name}`} onClick={() => onRows(added(rows, l))}>
              {on ? 'On tablet' : 'Add'}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
