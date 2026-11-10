// A device's touch controls: each a button for one light of the house, picked from its catalogue, on or off.
import { useEffect, useState } from 'preact/hooks';
import { getDeviceControls, putDeviceControls } from '../../api/deviceControls';
import { onResync, onScreenChanged } from '../../session/live';
import type { ListedDevice } from '../../api/types';
import { actionFor, added, changed, complete, draftOf, LABEL_MOST, moved, pickName, REFUSED, removed, type Row } from './controlRows';
import { lights } from './controls';

type Said = { tone: 'ok' | 'bad'; text: string } | null;

function RowEditor({ row, at, last, onRow }: { row: Row; at: number; last: boolean; onRow: (next: Row[] | ((r: Row[]) => Row[])) => void }) {
  const shown = lights.value.state === 'ready' ? lights.value.lights : [];
  const known = shown.some((l) => l.entity_id === row.entity_id);
  return (
    <div class="ctl-row">
      <input type="text" value={row.label} maxLength={LABEL_MOST} aria-label="Button label" autocomplete="off"
        onInput={(e) => onRow((rows) => changed(rows, at, { label: e.currentTarget.value }))} />
      <select value={row.action} aria-label="What it does" disabled={row.entity_id.startsWith('scene.')}
        onChange={(e) => onRow((rows) => changed(rows, at, { action: e.currentTarget.value as Row['action'] }))}>
        {row.entity_id.startsWith('scene.') ? <option value="scene.turn_on">Turn on</option> : (
          <>
            <option value="light.turn_on">Turn on</option>
            <option value="light.turn_off">Turn off</option>
          </>
        )}
      </select>
      <select value={row.entity_id} aria-label="Which light or scene"
        onChange={(e) => onRow((rows) => changed(rows, at, { entity_id: e.currentTarget.value, action: actionFor(e.currentTarget.value, row.action) }))}>
        {!known && <option value={row.entity_id}>{row.entity_id} (not found)</option>}
        {shown.map((l) => <option key={l.entity_id} value={l.entity_id}>{pickName(l)}</option>)}
      </select>
      <span class="ctl-move">
        <button class="btn sm ghost" type="button" aria-label="Move up" disabled={at === 0} onClick={() => onRow((rows) => moved(rows, at, -1))}>Up</button>
        <button class="btn sm ghost" type="button" aria-label="Move down" disabled={last} onClick={() => onRow((rows) => moved(rows, at, 1))}>Down</button>
        <button class="btn sm ghost" type="button" aria-label="Remove" onClick={() => onRow((rows) => removed(rows, at))}>Remove</button>
      </span>
    </div>
  );
}

export function ControlsEditor({ d }: { d: ListedDevice }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const read = (then?: Said) => getDeviceControls(d.id).then((got) => {
    setRows(draftOf(got.device_controls));
    setVersion(got.piece_version);
    if (then) setSaid(then);
  }, () => setSaid({ tone: 'bad', text: "Couldn't read this screen's controls." }));
  useEffect(() => {
    void read();
  }, [d.id]);
  useEffect(() => {
    const again = () => void read();
    return (() => {
      const stops = [onScreenChanged((device) => device === d.id && again()), onResync(again)];
      return () => stops.forEach((stop) => stop());
    })();
  }, [d.id]);
  const state = lights.value;
  const save = async () => {
    if (!rows) return;
    setBusy(true);
    try {
      const got = await putDeviceControls(d.id, rows, version);
      if (got === 'stale') await read({ tone: 'bad', text: 'The list changed while you were editing it, so nothing was saved. This is what it is now.' });
      else if ('reason' in got) setSaid({ tone: 'bad', text: REFUSED[got.reason] });
      else {
        setRows(draftOf(got.device_controls));
        setVersion(got.piece_version);
        setSaid({ tone: 'ok', text: 'Saved. The screen has them on its next read.' });
      }
    } catch {
      setSaid({ tone: 'bad', text: "That didn't go through. Nothing changed." });
    }
    setBusy(false);
  };
  if (!rows) return <div class="ctl"><span class="meta">{said ? said.text : 'Reading the controls…'}</span></div>;
  const first = state.state === 'ready' ? state.lights[0] : undefined;
  return (
    <div class="ctl">
      <b>Touch controls</b>
      {state.state === 'none' && <p class="meta">Connect Home Assistant to pick lights and scenes for this screen.</p>}
      {state.state === 'failed' && <p class="unk">couldn't read the house's lights and scenes</p>}
      {rows.length === 0 && state.state === 'ready' && <p class="meta">No controls yet.</p>}
      {rows.map((r, i) => <RowEditor key={r.name ?? `new-${i}`} row={r} at={i} last={i === rows.length - 1} onRow={(n) => setRows(typeof n === 'function' ? n(rows) : n)} />)}
      <div class="dc-act">
        <button class="btn sm" type="button" disabled={!first} onClick={() => setRows(added(rows, first))}>Add a control</button>
        <button class="btn primary sm" type="button" disabled={busy || !complete(rows)} onClick={() => void save()}>Save</button>
      </div>
      {said && <div class={`dc-note ${said.tone}`} role="status"><span>{said.text}</span></div>}
    </div>
  );
}
