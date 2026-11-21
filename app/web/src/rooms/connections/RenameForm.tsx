// The form that renames one connection. A blank name shows the kind's title. A kind that takes a description (a herdr
// machine) adds the owner's few words about what the connection reaches.
import { useState } from 'preact/hooks';
import type { HouseholdConnection } from '../../api/types';
import { kinds, rename } from './connections';
import { DESCRIPTION_MAX, takesDescription } from './describing';

export function RenameForm({ connection, onDone, onBack }: { connection: HouseholdConnection; onDone: () => void; onBack: () => void }) {
  const [label, setLabel] = useState(connection.label);
  const [description, setDescription] = useState(connection.description);
  const described = takesDescription(kinds.value, connection.kind);
  const submit = async (e: Event) => {
    e.preventDefault();
    if (await rename(connection, label.trim(), described ? description.trim() : undefined)) onDone();
  };
  return (
    <form class="cn-form" onSubmit={(e) => void submit(e)}>
      <label>
        <span class="meta">Name</span>
        <input type="text" value={label} maxLength={40} autocomplete="off" onInput={(e) => setLabel(e.currentTarget.value)} />
      </label>
      {described && (
        <label>
          <span class="meta">About this machine</span>
          <textarea value={description} maxLength={DESCRIPTION_MAX} rows={3} placeholder="Where it is and what it is for, so she can pick it for a job"
            onInput={(e) => setDescription(e.currentTarget.value)} />
        </label>
      )}
      <div class="dc-act">
        <button class="btn primary" type="submit">{described ? 'Save' : 'Rename'}</button>
        <button class="btn ghost" type="button" onClick={onBack}>Cancel</button>
      </div>
    </form>
  );
}
