// The selected device: what it is, who it is for, and, for a screen that takes touch controls, the way into its editor.
import type { ListedDevice } from '../../api/types';
import { ControlsEditor } from './ControlsEditor';
import { editing } from './devices';
import { itDoes, kindName, whoMark } from './sentence';

export function DevicePanel({ d }: { d: ListedDevice }) {
  if (editing.value && d.takes_controls) return <ControlsEditor d={d} onClose={() => (editing.value = false)} />;
  return (
    <div class="panel dv">
      <div class="dv-head">
        <h2>{d.name}</h2>
        <span class="meta">In {d.place.trim()}</span>
      </div>
      <dl class="dv-facts">
        <dt>Kind</dt><dd>{kindName(d.form)}</dd>
        <dt>Who it's for</dt><dd>{whoMark(d.audience)}</dd>
        <dt>It</dt><dd>{itDoes(d)}</dd>
        <dt>Last heard</dt><dd><span class="unk">Not recorded</span></dd>
      </dl>
      {d.takes_controls && <button class="btn" type="button" onClick={() => (editing.value = true)}>Edit controls</button>}
    </div>
  );
}
