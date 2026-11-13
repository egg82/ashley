// The ledger: a section per provider that has something to say in the window, then one quiet line for those that don't.
import type { SpendResponse } from '../../api/types';
import { quietOf, shown } from './ledger';
import { ProviderRow } from './ProviderRow';
import { whenOf, type Win } from './window';

export function Ledger({ s, win }: { s: SpendResponse; win: Win }) {
  const now = new Date(s.as_of);
  const quiet = quietOf(s, win);
  return (
    <section class="sp-ledger" aria-label="Ledger">
      <h2 class="label">Ledger · {whenOf(win)}</h2>
      {s.providers.filter((p) => shown(p, win)).map((p) => <ProviderRow key={p.provider} p={p} win={win} now={now} zone={s.zone} />)}
      {quiet.length > 0 && <p class="meta sp-quiet">No calls {whenOf(win)} from {quiet.join(', ')}.</p>}
    </section>
  );
}
