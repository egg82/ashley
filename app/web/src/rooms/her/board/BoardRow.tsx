// One board row: what it is, what started it when she did it on her own (↳), when it last moved, and what the person
// can do with it from here. What a pressed action did, or why it did not, shows under the row.
import { useState } from 'preact/hooks';
import { agreeTo } from '../../../api/agree';
import { cancelWatch, undoAction } from '../../../api/board';
import { ApiError } from '../../../api/client';
import { readGlance } from '../../../session/house';
import { load as reloadSession } from '../../../session/session';
import { moment } from '../../memory/facts';
import { whyNotAgreed } from '../agreeWhy';
import { loadWork } from '../work';
import { KIND_WORD, where } from '../workRows';
import type { WorkItem } from '../../../api/types';
import { offers, undoneWord, undoResult, whyNot, type Offer } from './offers';

type Done = { note: string | null; alert: boolean };

function useAct() {
  const [state, setState] = useState<Done & { working: boolean }>({ working: false, note: null, alert: false });
  const run = async (work: () => Promise<string | null>, why: (status?: number, code?: string) => string = whyNot) => {
    setState({ working: true, note: null, alert: false });
    try {
      setState({ working: false, note: await work(), alert: false });
      void readGlance();
      await loadWork();
    } catch (error) {
      const status = error instanceof ApiError ? error.status : undefined;
      if (status === 401) void reloadSession();
      setState({ working: false, note: why(status, error instanceof ApiError ? error.code : undefined), alert: true });
      if (status === 404 || status === 409) void loadWork();
    }
  };
  return { ...state, run };
}

function focusComposer(): void {
  document.querySelector<HTMLTextAreaElement>('.her-room .compose textarea')?.focus();
}

function Action({ offer, act }: { offer: Offer; act: ReturnType<typeof useAct> }) {
  const busy = act.working;
  switch (offer.kind) {
    case 'agree':
      return <button class="agree-btn b-agree" type="button" disabled={busy} onClick={() => void act.run(async () => {
        await agreeTo({ proposal_id: offer.proposal });
        return null;
      }, whyNotAgreed)}>{busy ? 'Agreeing…' : 'Agree'}</button>;
    case 'reply':
      return offer.here ? <button class="btn sm ghost" type="button" onClick={focusComposer}>Reply</button> : null;
    case 'cancel':
      return <button class="btn sm ghost" type="button" disabled={busy} onClick={() => void act.run(async () => {
        await cancelWatch(offer.watch);
        return null;
      })}>{busy ? 'Cancelling…' : 'Cancel'}</button>;
    case 'undo':
      return <button class="btn sm ghost" type="button" disabled={busy} onClick={() => void act.run(async () =>
        undoResult((await undoAction(offer.action)).how))}>{busy ? 'Undoing…' : 'Undo'}</button>;
  }
}

function Sub({ item }: { item: WorkItem }) {
  const undone = undoneWord(item);
  const kind = item.kind === 'action' || item.kind === 'proposal' ? null : KIND_WORD[item.kind];
  return (
    <div class="meta b-sub">
      {kind && `${kind} · `}{item.state === 'stopped' ? 'Stopped · ' : ''}{moment(item.at)}
      {undone && <span class={`b-undone ${item.undone?.how ?? ''}`}> · {undone}</span>}
    </div>
  );
}

export function BoardRow({ item, cause, open }: { item: WorkItem; cause: string | null; open: number | null }) {
  const act = useAct();
  const href = where(item);
  const shown = offers(item, open);
  return (
    <li class={`b-row${item.undone && item.undone.how !== 'waiting_on_you' ? ' undone' : ''}`}>
      <div class="b-top">
        <div class="b-t">
          {href ? <a class="b-title" href={href}>{item.title}</a> : <span class="b-title">{item.title}</span>}
          {cause && <div class="b-cause"><span aria-hidden="true">↳ </span>{cause}</div>}
          <Sub item={item} />
          {shown.some((o) => o.kind === 'reply' && !o.here) && <div class="meta b-elsewhere">Reply to her where she asked</div>}
        </div>
        {shown.some((o) => o.kind !== 'reply' || o.here) && <div class="b-acts">{shown.map((o) => <Action key={o.kind} offer={o} act={act} />)}</div>}
      </div>
      {act.note && <p class={`b-note${act.alert ? ' alert' : ''}`} role={act.alert ? 'alert' : 'status'}>{act.note}</p>}
    </li>
  );
}
