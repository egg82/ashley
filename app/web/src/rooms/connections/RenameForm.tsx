// The form that renames one connection. A blank name shows the kind's title.
import { useState } from 'preact/hooks';
import type { HouseholdConnection } from '../../api/types';
import { rename } from './connections';

export function RenameForm({ connection, onDone, onBack }: { connection: HouseholdConnection; onDone: () => void; onBack: () => void }) {
  const [label, setLabel] = useState(connection.label);
  const submit = async (e: Event) => {
    e.preventDefault();
    if (await rename(connection, label.trim())) onDone();
  };
  return (
    <form class="cn-form" onSubmit={(e) => void submit(e)}>
      <label>
        <span class="meta">Name</span>
        <input type="text" value={label} maxLength={40} autocomplete="off" onInput={(e) => setLabel(e.currentTarget.value)} />
      </label>
      <div class="dc-act">
        <button class="btn primary" type="submit">Rename</button>
        <button class="btn ghost" type="button" onClick={onBack}>Cancel</button>
      </div>
    </form>
  );
}
