// The form that adds a connection of one kind, or replaces connection `replacing`: a label when the kind allows several,
// an address unless the kind has one, and a key or token. The key or token is never shown back and is cleared whatever
// the answer.
import { useState } from 'preact/hooks';
import type { ConnectionKindInfo } from '../../api/types';
import { connect, connecting } from './connections';

export function KindForm({ kind, base, replacing, onDone, onBack }: {
  kind: ConnectionKindInfo;
  base: string;
  replacing?: number;
  onDone: () => void;
  onBack: () => void;
}) {
  const [label, setLabel] = useState('');
  const [address, setAddress] = useState(base);
  const [secret, setSecret] = useState('');
  const submit = async (e: Event) => {
    e.preventDefault();
    const ok = await connect(kind, label.trim(), address.trim(), secret.trim(), replacing);
    setSecret('');
    if (ok) onDone();
  };
  return (
    <form class="cn-form" onSubmit={(e) => void submit(e)}>
      {replacing === undefined && kind.most > 1 && (
        <label>
          <span class="meta">Name</span>
          <input type="text" value={label} maxLength={40} placeholder="work, laptop…" autocomplete="off"
            onInput={(e) => setLabel(e.currentTarget.value)} />
        </label>
      )}
      {kind.takes_address && (
        <label>
          <span class="meta">Address</span>
          <input type="url" value={address} placeholder={kind.address_placeholder} autocomplete="off"
            onInput={(e) => setAddress(e.currentTarget.value)} />
        </label>
      )}
      <label>
        <span class="meta">{kind.secret_label}</span>
        <input type="password" value={secret} autocomplete="off" onInput={(e) => setSecret(e.currentTarget.value)} />
      </label>
      <div class="dc-act">
        <button class="btn primary" type="submit" disabled={connecting.value !== null || (kind.takes_address && !address.trim()) || !secret.trim()}>
          {base ? 'Replace' : 'Connect'}
        </button>
        <button class="btn ghost" type="button" onClick={onBack}>{base ? 'Cancel' : 'Back'}</button>
        {connecting.value === kind.name && <span class="meta">Asking {kind.title}…</span>}
      </div>
    </form>
  );
}
