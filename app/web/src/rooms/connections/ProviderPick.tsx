// The provider an OpenAI-compatible connection is: one the model catalogue lists (its base URL prefills the address
// and its calls are priced from the catalogue) or a custom address, whose calls are unpriced.
import { useEffect, useState } from 'preact/hooks';
import { getCatalogue } from '../../api/catalogue';
import { pick, pickable, type Pickable, type Picked } from './providerChoice';

const CUSTOM = '';

export function ProviderPick({ picked, pattern, onPick }: {
  picked: Picked;
  pattern: string | null | undefined;
  onPick: (next: Picked) => void;
}) {
  const [from, setFrom] = useState<Pickable[] | null>(null);
  const [unread, setUnread] = useState(false);
  useEffect(() => {
    getCatalogue().then((c) => setFrom(pickable(c.catalogue_providers)), () => setUnread(true));
  }, []);
  const choose = (provider: string) => {
    const list = from ?? [];
    onPick(pick(picked, list.find((p) => p.provider === provider) ?? null, list, pattern));
  };
  return (
    <label>
      <span class="meta">Provider</span>
      <select value={picked.provider ?? CUSTOM} disabled={from === null && !unread} onChange={(e) => choose(e.currentTarget.value)}>
        <option value={CUSTOM}>Custom address (calls unpriced)</option>
        {(from ?? []).map((p) => <option key={p.provider} value={p.provider}>{p.name}</option>)}
      </select>
      {unread && <span class="meta unk">couldn’t read the model catalogue; a custom address still works</span>}
    </label>
  );
}
