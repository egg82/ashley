// Pairing: the admin pastes a device token made for this screen, once. The token is sent to the server, which keeps it
// in the kiosk's cookie; the page never stores it.
import { useState } from 'preact/hooks';
import { AshleyMark } from '../components/AshleyMark';
import { pair } from './state';

const FAILED = {
  refused: 'Not accepted. Use a device token, on the home network.',
  elsewhere: 'Open this page at her own address.',
  unreachable: "Can't reach her. Try again.",
};

export function Pairing() {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<keyof typeof FAILED | null>(null);
  const ready = !busy && token.trim().length > 0;
  return (
    <div class="k-pair">
      <form
        class="panel k-pair-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          setBusy(true);
          void pair(token.trim()).then((why) => {
            setBusy(false);
            setFailed(why);
            if (why === null) setToken('');
          });
        }}
      >
        <AshleyMark state="idle" size={96} />
        <h1>Pair this screen</h1>
        <label class="label" for="k-token">Device token</label>
        <input
          id="k-token"
          class="k-input"
          type="password"
          value={token}
          autocomplete="off"
          spellcheck={false}
          onInput={(e) => setToken(e.currentTarget.value)}
        />
        {failed && <p class="k-err" role="alert">{FAILED[failed]}</p>}
        <button class="btn primary" type="submit" disabled={!ready}>{busy ? 'Pairing…' : 'Pair'}</button>
      </form>
    </div>
  );
}
