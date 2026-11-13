// The control picked on the tablet: its label, what it does, where it sits, and taking it off.
import { actionFor, changed, LABEL_MOST, moved, removed, type Row } from './controlRows';

export function CardEditor({ rows, at, onRows, onDone }: { rows: Row[]; at: number; onRows: (rows: Row[]) => void; onDone: () => void }) {
  const row = rows[at]!;
  const scene = row.entity_id.startsWith('scene.');
  return (
    <div class="ce">
      <label class="ce-field">
        <span class="label">Label</span>
        <input type="text" value={row.label} maxLength={LABEL_MOST} autocomplete="off" onInput={(e) => onRows(changed(rows, at, { label: e.currentTarget.value }))} />
      </label>
      <label class="ce-field">
        <span class="label">Does</span>
        <select value={actionFor(row.entity_id, row.action)} disabled={scene} onChange={(e) => onRows(changed(rows, at, { action: e.currentTarget.value as Row['action'] }))}>
          {scene ? <option value="scene.turn_on">Run scene</option> : (
            <>
              <option value="light.toggle">Toggle</option>
              <option value="light.turn_on">Turn on</option>
              <option value="light.turn_off">Turn off</option>
            </>
          )}
        </select>
      </label>
      <span class="meta ce-entity">{row.entity_id}</span>
      <span class="ce-acts">
        <button class="btn sm ghost" type="button" disabled={at === 0} onClick={() => onRows(moved(rows, at, -1))}>Earlier</button>
        <button class="btn sm ghost" type="button" disabled={at === rows.length - 1} onClick={() => onRows(moved(rows, at, 1))}>Later</button>
        <button class="btn sm ghost" type="button" onClick={() => { onRows(removed(rows, at)); onDone(); }}>Remove</button>
      </span>
    </div>
  );
}
