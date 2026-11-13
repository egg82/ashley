// The form that adds a connection of one kind, or replaces connection `replacing`: a label when the kind allows several,
// the catalogue provider when the kind is priced from the model catalogue, an address unless the kind has one, and a
// key or token. The key or token is never shown back and is cleared whatever the answer.
import { useState } from 'preact/hooks';
import type { ConnectionKindInfo } from '../../api/types';
import { connect, connecting, held } from './connections';
import { ProviderPick } from './ProviderPick';

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
  const [provider, setProvider] = useState<string | null>(held.value.find((c) => c.id === replacing)?.catalogue_provider ?? null);
  const submit = async (e: Event) => {
    e.preventDefault();
    const priced = kind.picks_catalogue_provider ? provider : undefined;
    const ok = await connect(kind, label.trim(), address.trim(), secret.trim(), replacing, priced);
    setSecret('');
    if (ok) onDone();
  };
  const named = replacing === undefined && kind.most > 1;
  return (
    <form class="cn-form" onSubmit={(e) => void submit(e)}>
      {kind.picks_catalogue_provider && (
        <ProviderPick picked={{ provider, address, label }} pattern={kind.label_pattern} onPick={(next) => {
          setProvider(next.provider);
          setAddress(next.address);
          if (named) setLabel(next.label);
        }} />
      )}
      {named && (
        <label>
          <span class="meta">Name</span>
          <input type="text" value={label} maxLength={40} placeholder={kind.label_pattern ? 'openrouter, local…' : 'work, laptop…'}
            pattern={kind.label_pattern ?? undefined} required={!!kind.label_pattern} autocomplete="off"
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
