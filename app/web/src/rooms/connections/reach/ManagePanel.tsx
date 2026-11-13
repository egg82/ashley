// The opened row: what the connection is and holds, who holds it and whether that can move, what it reaches, its settings,
// and the actions on it. Removing opens its own confirmation in place of the actions.
import type { ComponentChildren } from 'preact';
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { move } from '../connections';
import { openRename } from '../picking';
import { accounts } from '../proton';
import { stateOf } from '../protonSteps';
import { runFix, replaceWords } from './fixes.ts';
import { holdsLine, stayReason } from './holder.ts';
import { scopeLabel } from './needs.ts';
import { RemoveConfirm } from './RemoveConfirm';
import { Resources } from './Resources';
import { hostOf, holderOf } from './sentence.ts';
import { SettingsDigest } from './SettingsDigest';
import { removing, startRemoving } from './state';

function Item({ term, children }: { term: string; children: ComponentChildren }) {
  return <div class="rr-item"><dt class="label">{term}</dt><dd>{children}</dd></div>;
}

function Address({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  if (kind.connect === 'bridge') return <Item term="Account">{stateOf(accounts.value.get(c.id)) ?? <span class="unk">not read</span>}</Item>;
  const pinned = c.base_url.includes('#sha256=');
  return <Item term="Address"><span class="rr-mono">{kind.takes_address ? c.base_url.replace(/#.*$/, '') : hostOf(c.base_url)}</span>{pinned && <span class="meta"> · pinned to one certificate</span>}</Item>;
}

function Held({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  const why = stayReason(c, kind);
  return (
    <Item term="Held by">
      <div><b>{c.personal ? `${holderOf(c)} alone` : 'The household'}</b> <span class="meta">· {holdsLine(c)}</span></div>
      <div class="dc-act">
        {c.can_hand_over && <button class="btn sm" type="button" onClick={() => void move(c, 'household')}>Hand to the household</button>}
        {c.can_take_back && <button class="btn sm" type="button" onClick={() => void move(c, 'person')}>Take back</button>}
        {why && <span class="meta">{why}</span>}
      </div>
    </Item>
  );
}

function Access({ c }: { c: HouseholdConnection }) {
  if (c.scopes.length === 0 && c.missing_scopes.length === 0) return null;
  return (
    <Item term="Access">
      <span class="rr-chips">
        {c.scopes.map((s) => <span key={s} class="rr-chip" title={s}>{scopeLabel(s)}</span>)}
        {c.missing_scopes.map((s) => <span key={s} class="rr-chip missing" title={s}>{scopeLabel(s)} · not granted</span>)}
      </span>
    </Item>
  );
}

function Actions({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  if (!c.can_change) return <p class="meta">Only {holderOf(c)} can change this.</p>;
  const replace = replaceWords(kind);
  return (
    <div class="dc-act rr-actions">
      <button class="btn sm" type="button" disabled={replace.fix === 'oauth' && !kind.set_up} onClick={() => runFix(replace.fix, c, kind)}>{replace.label}</button>
      <button class="btn sm" type="button" onClick={() => openRename(c)}>Rename</button>
      <button class="btn sm danger" type="button" onClick={() => startRemoving(c.id)}>Remove…</button>
    </div>
  );
}

export function ManagePanel({ c, kind }: { c: HouseholdConnection; kind: ConnectionKindInfo }) {
  return (
    <div class="rr-manage-panel" id={`m${c.id}`}>
      <dl class="panel rr-items">
        <Address c={c} kind={kind} />
        <Item term="Secret"><span class="meta">Stored, never shown.</span></Item>
        <Held c={c} kind={kind} />
        <Access c={c} />
        {c.resources.length > 0 && <Item term="Mailboxes"><Resources c={c} /></Item>}
        {kind.has_settings && <Item term="Settings"><SettingsDigest id={c.id} /></Item>}
      </dl>
      {removing.value === c.id ? <RemoveConfirm c={c} kind={kind} /> : <Actions c={c} kind={kind} />}
    </div>
  );
}
