// The step for a kind connected through its service's own consent screen: a name when the kind allows several, then on to
// the service. Nothing is typed that is a secret; a kind this app cannot connect says so and offers nothing.
import { useState } from 'preact/hooks';
import type { ConnectionKindInfo } from '../../api/types';
import { connecting, defaultHolder, type Holder } from './connections';
import { connectOAuth } from './oauth';

export function OAuthForm({ kind, onBack }: { kind: ConnectionKindInfo; onBack: () => void }) {
  const [label, setLabel] = useState('');
  const [holder, setHolder] = useState<Holder>(defaultHolder(kind));
  const submit = (e: Event) => {
    e.preventDefault();
    void connectOAuth(kind, label.trim(), holder);
  };
  return (
    <form class="cn-form" onSubmit={submit}>
      {kind.most > 1 && (
        <label>
          <span class="meta">Name</span>
          <input type="text" value={label} maxLength={40} placeholder="work, laptop…" autocomplete="off"
            onInput={(e) => setLabel(e.currentTarget.value)} />
        </label>
      )}
      {kind.holders.length > 1 && (
        <fieldset class="cn-holder">
          <legend class="meta">Who holds it</legend>
          <label><input type="radio" name="holder" checked={holder === 'person'} onChange={() => setHolder('person')} /> Just me</label>
          <label><input type="radio" name="holder" checked={holder === 'household'} onChange={() => setHolder('household')} /> The household</label>
        </fieldset>
      )}
      {!kind.set_up && <p class="cn-refused" role="alert">{kind.title} isn’t set up here, so it can’t be connected.</p>}
      <div class="dc-act">
        <button class="btn primary" type="submit" disabled={!kind.set_up || connecting.value !== null}>Connect with {kind.title}</button>
        <button class="btn ghost" type="button" onClick={onBack}>Back</button>
        {connecting.value === kind.name && <span class="meta">Going to {kind.title}…</span>}
      </div>
    </form>
  );
}
