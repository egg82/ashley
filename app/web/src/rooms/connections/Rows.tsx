// One connected service as a compact row: a mark, what it is and where, when it last answered, and a ⋯ for the rest.
import type { ComponentChildren } from 'preact';
import type { ConnectionKindInfo, HouseholdConnection, LinkedAccount } from '../../api/types';
import { unlink } from './accounts';
import { connecting, disconnect, move } from './connections';
import { connectOAuth, isOAuth } from './oauth';
import { openForm, openRename } from './picking';
import { accounts, isBridge } from './proton';
import { stateOf } from './protonSteps';
import { RowMenu, type RowAction } from './RowMenu';
import { HaSummary } from './settings/HaSummary';
import { WhoFor } from './WhoFor';

const ANSWERED = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
const ADDED = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

const SYSTEM: Record<string, string> = { oidc: 'OIDC', home_assistant: 'Home Assistant', discord: 'Discord' };

function Row({ title, mine, sub, when, actions, menu }: {
  title: string;
  mine: boolean;
  sub: ComponentChildren;
  when?: ComponentChildren;
  actions?: readonly RowAction[];
  menu?: string;
}) {
  return (
    <div class="cn-row">
      <span class={`cn-mark${mine ? ' mine' : ''}`} aria-hidden="true">{title.slice(0, 1).toUpperCase()}</span>
      <div class="cn-main">
        <b>{title}</b>
        <div class="meta cn-sub">{sub}</div>
      </div>
      {when && <div class="meta cn-when">{when}</div>}
      {actions && menu && <RowMenu label={menu} actions={actions} />}
    </div>
  );
}

/** The scope a service granted, by the last part of its name (`https://…/auth/gmail.readonly` is `gmail.readonly`). */
function scopeName(scope: string): string {
  return scope.split('/').pop() ?? scope;
}

function Needs({ kind, c }: { kind: ConnectionKindInfo; c: HouseholdConnection }) {
  if (c.needs === 'login') {
    return (
      <div class="dc-act">
        <span class="cn-needs">Proton signed this account out; log in again</span>
        <button class="btn sm" type="button" onClick={() => openForm(kind, c.base_url, false, c.id)}>Log in</button>
      </div>
    );
  }
  if (c.needs !== 'reconnect') return null;
  return (
    <div class="dc-act">
      <span class="cn-needs">{kind.title} turned the connection away; connect it again</span>
      <button class="btn sm" type="button" disabled={!kind.set_up || connecting.value !== null}
        onClick={() => void connectOAuth(kind, c.label, c.personal ? 'person' : 'household')}>Reconnect</button>
    </div>
  );
}

/** What a connection reaches, each once: its owner's own get a Just me | Household switch, a household's are only named. */
function Resources({ c }: { c: HouseholdConnection }) {
  if (c.resources.length === 0) return null;
  if (!c.personal) return <div class="cn-scopes">{c.resources.map((r) => r.name).join(', ')}</div>;
  return (
    <>
      <p class="cn-key"><b>Just me:</b> she talks about it only with you. <b>Household:</b> anyone at home can ask, including on the hallway screen.</p>
      <div class="cn-addrs">{c.resources.map((r) => <WhoFor key={r.ref} c={c} r={r} />)}</div>
    </>
  );
}

function sizeOf(c: HouseholdConnection): string {
  return `${c.resources.length} ${c.resources.length === 1 ? 'address' : 'addresses'}`;
}

/** What a Proton card says under its name: how many addresses, and how far Bridge has got. */
function bridgeSub(c: HouseholdConnection): string {
  const state = c.needs === null ? stateOf(accounts.value.get(c.id)) : null;
  return [c.resources.length > 0 ? sizeOf(c) : null, state].filter((p) => p !== null).join(' · ');
}

function KindSub({ kind, c }: { kind: ConnectionKindInfo; c: HouseholdConnection }) {
  return (
    <>
      <div>{kind.takes_address ? <>{kind.what} · <span class="cn-url">{c.base_url}</span></> : isBridge(kind) ? bridgeSub(c) : kind.what}</div>
      {isOAuth(kind) && c.scopes.length > 0 && <div class="cn-scopes">Granted: {c.scopes.map(scopeName).join(', ')}</div>}
      {c.missing_scopes.length > 0 && (
        <div class="cn-needs">Not granted: {c.missing_scopes.map(scopeName).join(', ')}. Reconnecting can grant {c.missing_scopes.length > 1 ? 'them' : 'it'}.</div>
      )}
      <Resources c={c} />
      <Needs kind={kind} c={c} />
      {kind.has_settings && !c.personal && <HaSummary id={c.id} />}
    </>
  );
}

function replaceAction(kind: ConnectionKindInfo, c: HouseholdConnection): RowAction {
  if (isBridge(kind)) return { label: 'Log in again', onPick: () => openForm(kind, c.base_url, false, c.id) };
  return isOAuth(kind)
    ? { label: 'Reconnect', onPick: () => void connectOAuth(kind, c.label, c.personal ? 'person' : 'household') }
    : { label: `Replace ${kind.secret_noun}`, onPick: () => openForm(kind, c.base_url, false, c.id) };
}

function moveActions(c: HouseholdConnection): RowAction[] {
  return [
    ...(c.can_hand_over ? [{ label: 'Hand to the household', onPick: () => void move(c, 'household') }] : []),
    ...(c.can_take_back ? [{ label: 'Take back', onPick: () => void move(c, 'person') }] : []),
  ];
}

export function KindRow({ kind, c }: { kind: ConnectionKindInfo; c: HouseholdConnection }) {
  const checked = ANSWERED.format(new Date(c.checked_at));
  const added = c.added_by ? `Added by ${c.added_by.name}` : 'Added';
  return (
    <Row title={c.label || kind.title} mine={c.personal} menu={`${c.label || kind.title} actions`}
      sub={<KindSub kind={kind} c={c} />}
      when={<><div><i class={`cn-dot${c.needs ? ' stale' : ''}`} />{c.needs ? 'Needs attention' : 'Working'} · checked {checked}</div><div class="cn-added">{added} · {ADDED.format(new Date(c.added_at))}</div></>}
      actions={[
        replaceAction(kind, c),
        ...moveActions(c),
        { label: 'Rename', onPick: () => openRename(c) },
        { label: 'Remove', onPick: () => void disconnect(c) },
      ]} />
  );
}

export function DiscordRow({ account }: { account: LinkedAccount }) {
  return (
    <Row title="Discord" mine menu="Discord actions"
      sub={account.handle ? `Linked as @${account.handle}` : 'Linked'}
      when="Only you see your DMs with her"
      actions={account.unlinkable ? [{ label: 'Unlink', onPick: () => void unlink(account.id) }] : undefined} />
  );
}

export function AccountRow({ account }: { account: LinkedAccount }) {
  return (
    <Row title={SYSTEM[account.system] ?? account.system} mine
      sub={account.system === 'oidc' ? 'you sign in with this' : (account.handle ?? 'linked by an admin')} />
  );
}
