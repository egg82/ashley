// What could be added: each offered kind not yet held (or held fewer times than allowed), in its own words, and the one
// action that starts it. Discord's link is here too while it is not linked.
import { accounts, canLink, linkDiscord } from '../accounts';
import { addable, type Choice } from '../choices';
import { connectionsState, held, kinds, ofKind } from '../connections';
import { openForm } from '../picking';
import { Avatar } from './Avatar';

function why(choice: Choice): string | null {
  if (choice.kind) return connectionsState.value === 'off' || !choice.kind.set_up ? 'not set up here' : null;
  return canLink.value ? null : 'not set up here';
}

/** "You have 1 of up to 5." for a kind that can be held more than once. */
function haveOf(choice: Choice): string | null {
  const kind = choice.kind;
  return kind && kind.most > 1 ? `You have ${ofKind(kind.name).length} of up to ${kind.most}.` : null;
}

function Option({ choice }: { choice: Choice }) {
  const blocked = why(choice);
  const have = haveOf(choice);
  const start = () => (choice.kind ? openForm(choice.kind, '', false) : void linkDiscord());
  return (
    <li class="rr-add">
      <Avatar kind={choice.id} title={choice.title} ghost />
      <p class="rr-add-says"><b>{choice.title}</b>: {blocked ? <span class="unk">{blocked}</span> : choice.blurb}{have && ` ${have}`}</p>
      <button class="btn" type="button" disabled={blocked !== null} aria-label={`Add ${choice.title}`} onClick={start}>Add…</button>
    </li>
  );
}

export function CouldAdd() {
  const choices = addable(kinds.value, held.value, accounts.value);
  if (choices.length === 0) return null;
  return (
    <section class="rr-group" id="g-add">
      <h2 class="rr-head">Could be added</h2>
      <ul class="rr-adds">{choices.map((c) => <Option key={c.id} choice={c} />)}</ul>
    </section>
  );
}

