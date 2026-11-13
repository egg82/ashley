// Appears once something changed: what changed, and Save or Undo. A save that came to nothing says so here.
import { household, householdSaid, householdSaving, saveHousehold } from '../../household/household';
import { changedLabels, draftOf, requestOf } from './draft';
import { draft, undo } from './state';

export function SaveBar() {
  const d = draft.value;
  const h = household.value;
  if (!d || !h) return null;
  const changed = changedLabels(d, draftOf(h));
  const said = householdSaid.value;
  const note = said === 'saved' ? 'Saved. She goes by it from her next reply.' : said === 'failed' ? "That didn't go through. Nothing changed." : null;
  if (!changed.length && !note) return null;
  const save = () => {
    const request = requestOf(d);
    if (typeof request === 'string') householdSaid.value = 'location';
    else void saveHousehold(request);
  };
  return (
    <div class="hh-savebar" role="group" aria-label="Unsaved changes">
      {changed.length > 0 && <span class="hh-changed">Changed: {changed.join(', ')}</span>}
      {note && <span class={said === 'failed' ? 'hh-changed bad' : 'hh-changed'} role={said === 'failed' ? 'alert' : 'status'}>{note}</span>}
      <span class="hh-save-acts">
        {changed.length > 0 && <button class="btn sm primary" type="button" disabled={householdSaving.value} onClick={save}>Save changes</button>}
        {changed.length > 0 && <button class="btn sm ghost" type="button" onClick={undo}>Undo</button>}
        {!changed.length && <button class="btn sm ghost" type="button" onClick={() => (householdSaid.value = null)}>Dismiss</button>}
      </span>
    </div>
  );
}
