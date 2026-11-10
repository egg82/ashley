// "Add a service": a modal with a search over what is not connected yet, each with its description and whether it is
// yours or the household's. Choosing one opens its form here; Discord goes to Discord. The same modal replaces a key.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { ConnectionKindInfo } from '../../api/types';
import { accounts, canLink, linkDiscord } from './accounts';
import { addable, matching, whose, type Choice, type Whose } from './choices';
import { connectionsState, held, kinds } from './connections';
import { BridgeForm } from './BridgeForm';
import { KindForm } from './KindForm';
import { OAuthForm } from './OAuthForm';
import { isOAuth } from './oauth';
import { Refusal } from './Notice';
import { isBridge } from './proton';
import { RenameForm } from './RenameForm';
import { cancelPicker, closePicker, openForm, openList, picking, type Picking } from './picking';

const TAG: Record<Whose, string> = { yours: 'Yours', household: 'Household', either: 'Yours or the household’s' };

function Tag({ whose: who }: { whose: Whose }) {
  return <span class={`pill cn-tag${who === 'household' ? '' : ' mine'}`}>{TAG[who]}</span>;
}

function Option({ choice, why }: { choice: Choice; why: string | null }) {
  const pick = () => {
    if (choice.kind) openForm(choice.kind, '', true);
    else {
      closePicker();
      void linkDiscord();
    }
  };
  return (
    <li>
      <button class="cn-opt" type="button" disabled={why !== null} onClick={pick}>
        <span class={`cn-mark${choice.whose === 'household' ? '' : ' mine'}`} aria-hidden="true">{choice.title.slice(0, 1).toUpperCase()}</span>
        <span class="cn-opt-main">
          <span class="cn-opt-head"><b>{choice.title}</b><Tag whose={choice.whose} /></span>
          <span class="meta">{choice.what}</span>
          <span class="cn-blurb">{why ? <span class="unk">{why}</span> : choice.blurb}</span>
        </span>
      </button>
    </li>
  );
}

/** Why a choice cannot be taken now, or null. */
function unavailable(choice: Choice): string | null {
  if (choice.kind) return connectionsState.value === 'off' || !choice.kind.set_up ? 'not set up here' : null;
  return canLink.value ? null : 'not set up here';
}

function List() {
  const [query, setQuery] = useState('');
  const all = addable(kinds.value, held.value, accounts.value);
  const shown = matching(all, query);
  return (
    <>
      <input class="cn-search" type="search" value={query} placeholder="Search services" aria-label="Search services"
        autocomplete="off" onInput={(e) => setQuery(e.currentTarget.value)} />
      {shown.length > 0 && <ul class="cn-opts">{shown.map((c) => <Option key={c.id} choice={c} why={unavailable(c)} />)}</ul>}
      {!shown.length && <p class="meta cn-none">{all.length ? `Nothing offered matches “${query.trim()}”.` : 'Everything she offers is connected.'}</p>}
    </>
  );
}

/** The name of the connection being logged in to again, when there is one. */
function againLabel(replacing: number | undefined): string | undefined {
  return replacing === undefined ? undefined : held.value.find((c) => c.id === replacing)?.label;
}

function FormStep({ kind, base, fromList, replacing }: { kind: ConnectionKindInfo; base: string; fromList: boolean; replacing?: number }) {
  return (
    <>
      <div class="cn-formhead">
        <Tag whose={whose(kind)} />
        <span class="meta">{kind.what}</span>
      </div>
      {!base && <p class="cn-blurb">{kind.blurb}</p>}
      <Refusal kind={kind} />
      {isBridge(kind)
        ? <BridgeForm kind={kind} again={againLabel(replacing)} onDone={closePicker} onBack={fromList ? openList : cancelPicker} />
        : isOAuth(kind)
          ? <OAuthForm kind={kind} onBack={fromList ? openList : cancelPicker} />
          : <KindForm kind={kind} base={base} replacing={replacing} onDone={closePicker} onBack={fromList ? openList : cancelPicker} />}
    </>
  );
}

function heading(p: Picking): string {
  if (p.step === 'list') return 'Add a service';
  if (p.step === 'rename') return `Rename ${p.connection.label || p.connection.kind}`;
  if (isBridge(p.kind)) return p.replacing === undefined ? `Connect ${p.kind.title}` : `Log in to ${p.kind.title} again`;
  return p.base ? `Replace ${p.kind.title}’s ${p.kind.secret_noun}` : `Connect ${p.kind.title}`;
}

export function Picker({ at }: { at: Picking }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    d.showModal();
    d.addEventListener('close', cancelPicker);
    return () => {
      d.removeEventListener('close', cancelPicker);
      if (d.open) d.close();
    };
  }, []);
  return (
    <dialog class="cn-dialog" ref={dialog} aria-label={heading(at)}
      onClick={(e) => e.target === dialog.current && cancelPicker()}>
      <div class="cn-dhead">
        <h2>{heading(at)}</h2>
        <button class="btn sm ghost" type="button" aria-label="Close" onClick={cancelPicker}>✕</button>
      </div>
      <div class="cn-dbody">
        {at.step === 'list' && <List />}
        {at.step === 'form' && <FormStep kind={at.kind} base={at.base} fromList={at.fromList} replacing={at.replacing} />}
        {at.step === 'rename' && <RenameForm connection={at.connection} onDone={closePicker} onBack={cancelPicker} />}
      </div>
    </dialog>
  );
}

export function PickerHost() {
  const at = picking.value;
  return at ? <Picker at={at} /> : null;
}
