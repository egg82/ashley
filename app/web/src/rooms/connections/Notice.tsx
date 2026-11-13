// What the last change came to, said once above the list: a Discord link's return or unlink, or a kind connected,
// replaced or removed. A refusal is also said inside the picker, where the person is when it happens.
import type { ConnectionKindInfo } from '../../api/types';
import { said } from './accounts';
import { connectionsSaid } from './connections';
import type { ConnectOutcome } from './connectOutcome';
import { returned } from './oauth';

type Said = NonNullable<typeof said.value>;

const DISCORD: Record<Said, [string, 'ok' | 'bad' | '']> = {
  linked: ['Discord linked.', 'ok'],
  unlinked: ["Discord unlinked. She won't answer DMs from it now.", 'ok'],
  cancelled: ['Cancelled at Discord. Nothing changed.', ''],
  taken: ["That Discord account is someone else's here. Nothing changed.", 'bad'],
  wrong_person: ['Someone else started that link. Nothing changed.', 'bad'],
  unavailable: ["Couldn't reach Discord or Ashley. Nothing changed.", 'bad'],
  failed: ["Linking didn't go through. Nothing changed.", 'bad'],
  start_failed: ["Couldn't start linking. Nothing changed.", 'bad'],
  unlink_failed: ["Unlinking didn't go through. It's still linked.", 'bad'],
  unreachable: ["Can't reach her right now. Nothing changed.", 'bad'],
};

const CONNECT: Record<ConnectOutcome, [string, 'ok' | 'bad' | '']> = {
  connected: ['Connected.', 'ok'],
  cancelled: ['Cancelled at the service. Nothing changed.', ''],
  wrong_person: ['Someone else started that connection. Nothing changed.', 'bad'],
  refused: ['The service turned the connection away. Nothing changed.', 'bad'],
  label_taken: ['You already have one of those under that name. Nothing changed.', 'bad'],
  too_many: ['You already have as many of those as can be connected. Nothing changed.', 'bad'],
  unavailable: ["Couldn't reach the service or Ashley. Nothing changed.", 'bad'],
  failed: ["Connecting didn't go through. Nothing changed.", 'bad'],
};

const MOVED: Record<string, string> = {
  handed_over: 'Handed to the household. What it reaches is shared with them now.',
  taken_back: 'Taken back. What it reaches is kept for you again.',
  shared: 'Shared with the household.',
  kept: 'Kept for you alone.',
};

const FAILED: Record<string, string> = {
  not_yours: 'Only the person who added it can take it back. Nothing changed.',
  move_label_taken: 'The household already has one of those under that name. Rename this one first. Nothing changed.',
  move_too_many: 'The household already has as many of those as can be connected. Nothing changed.',
  not_set_up: 'That isn’t set up here yet, so it can’t be connected. Nothing changed.',
  remove_failed: 'Removing didn’t go through. It’s still connected.',
  failed: 'That didn’t go through. Nothing changed.',
  label_taken: 'You already have one of those under that name. Nothing changed.',
  too_many: 'You already have as many of those as can be connected. Nothing changed.',
  bad_label: 'That name is what routes call it: lowercase letters, digits, - and _, and not a provider’s own. Nothing changed.',
};

function Line({ text, tone, onDismiss }: { text: string; tone: 'ok' | 'bad' | ''; onDismiss: () => void }) {
  return (
    <div class={`dc-note ${tone}`} role="status">
      <span>{text}</span>
      <button class="btn sm ghost" type="button" onClick={onDismiss}>Dismiss</button>
    </div>
  );
}

/** What a kind's last change came to, in the kind's own words; null when it is not about `kinds`. */
function kindLine(kinds: readonly ConnectionKindInfo[]): { text: string; ok: boolean } | null {
  const s = connectionsSaid.value;
  const kind = s && kinds.find((k) => k.name === s.kind);
  if (!s || !kind) return null;
  const ok = s.said === 'connected' || s.said === 'removed' || s.said === 'renamed' || s.said in MOVED;
  const text = s.said === 'connected' ? kind.connected : s.said === 'removed' ? kind.removed : s.said === 'renamed' ? 'Renamed.' : (MOVED[s.said] ?? FAILED[s.said] ?? `${s.detail ?? ''} Nothing was saved.`);
  return { text, ok };
}

export function Notice({ kinds }: { kinds: readonly ConnectionKindInfo[] }) {
  const line = kindLine(kinds);
  const discord = said.value;
  const clear = () => (connectionsSaid.value = null);
  const back = returned.value;
  return (
    <>
      {discord && <Line text={DISCORD[discord][0]} tone={DISCORD[discord][1]} onDismiss={() => (said.value = null)} />}
      {back && <Line text={CONNECT[back][0]} tone={CONNECT[back][1]} onDismiss={() => (returned.value = null)} />}
      {line && <Line text={line.text} tone={line.ok ? 'ok' : 'bad'} onDismiss={clear} />}
    </>
  );
}

/** A refusal of `kind`, said where the person is while the picker covers the room. */
export function Refusal({ kind }: { kind: ConnectionKindInfo }) {
  const line = kindLine([kind]);
  return line && !line.ok ? <p class="cn-refused" role="alert">{line.text}</p> : null;
}
