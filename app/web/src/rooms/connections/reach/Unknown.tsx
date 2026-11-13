// The room when it has nothing true to show: the connections could not be read (no counts, since none are known), or none
// are connected yet.
import { herWord } from '../../../shell/her/state';
import { accounts, loadAccounts } from '../accounts';
import { addable } from '../choices';
import { held, kinds, loadConnections } from '../connections';
import { openForm } from '../picking';

export function retry(): void {
  void loadAccounts();
  void loadConnections();
}

/** `unreachable`: Ashley did not answer (a 503 or nothing); otherwise something she answered with failed. */
export function Down({ unreachable }: { unreachable: boolean }) {
  return (
    <div class="rr-down" role="alert">
      <span class="down-dock" data-dock />
      <div class="rr-down-says">
        {unreachable && <span class="her-word unreachable">{herWord.value}</span>}
        <h2>{unreachable ? 'Can’t reach Ashley.' : 'The connections didn’t load.'}</h2>
        <p>What she can reach isn’t known from here. Nothing was changed. Try again in a moment.</p>
        <button class="btn primary" type="button" onClick={retry}>Try again</button>
      </div>
      <div class="rr-unknown" aria-hidden="true">{[0, 1, 2].map((i) => <div key={i}><i /><span /><span /></div>)}</div>
    </div>
  );
}

/** The first kind she could start with, for the button on an empty room. */
export function Empty() {
  const first = addable(kinds.value, held.value, accounts.value).find((c) => c.kind?.set_up);
  return (
    <div class="rr-empty">
      <p>Connect the house, your money, your code or your mail, and she can start working in them. Each one says what she will do with it before you paste anything.</p>
      {first?.kind && <button class="btn primary" type="button" onClick={() => first.kind && openForm(first.kind, '', false)}>Connect {first.title}</button>}
    </div>
  );
}
