// A screen's touch controls: the tablet drawn as it will look, the house's lights and scenes to put on it, and a save bar
// that appears only once something differs from what is stored.
import { useState } from 'preact/hooks';
import type { ListedDevice } from '../../api/types';
import { CardEditor } from './CardEditor';
import { complete, MOST } from './controlRows';
import { lights } from './controls';
import { HouseControls } from './HouseControls';
import { Tablet } from './Tablet';
import { useControls } from './useControls';

export function ControlsEditor({ d, onClose }: { d: ListedDevice; onClose: () => void }) {
  const c = useControls(d.id);
  const [picked, setPicked] = useState<number | null>(null);
  const head = (
    <div class="dv-head">
      <h2>{d.name}: controls</h2>
      <span class="meta">What shows on its screen, in this order. At most {MOST}.</span>
    </div>
  );
  if (!c.rows) {
    return (
      <div class="panel dv">
        {head}
        {c.failed ? <span class="unk">Couldn't read this screen's controls</span> : <p class="meta">Reading the controls…</p>}
        <button class="btn sm ghost" type="button" onClick={onClose}>Back</button>
      </div>
    );
  }
  const pick = picked !== null && picked < c.rows.length ? picked : null;
  const shown = lights.value.state === 'ready' ? lights.value.lights : [];
  return (
    <div class="panel dv ced">
      {head}
      <Tablet rows={c.rows} place={d.place.trim()} name={d.name} picked={pick} lights={shown} onPick={setPicked} onRows={c.edit} />
      {pick !== null && <CardEditor rows={c.rows} at={pick} onRows={c.edit} onDone={() => setPicked(null)} />}
      {c.said && <div class={`dc-note ${c.said.tone}`} role="status"><span>{c.said.text}</span></div>}
      <div class={`ced-save${c.changed ? ' up' : ''}`} hidden={!c.changed && !c.busy}>
        <span>Controls changed, not saved</span>
        <button class="btn sm ghost" type="button" disabled={c.busy} onClick={() => { c.discard(); setPicked(null); }}>Discard</button>
        <button class="btn primary sm" type="button" disabled={c.busy || !complete(c.rows)} onClick={() => void c.save()}>Save</button>
      </div>
      <section class="ced-house">
        <span class="label">House controls</span>
        <HouseControls rows={c.rows} onRows={c.edit} />
      </section>
      <button class="btn sm ghost ced-back" type="button" disabled={c.changed} onClick={onClose}>Done</button>
    </div>
  );
}
