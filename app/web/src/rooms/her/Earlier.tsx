// The person's earlier conversations above the open one, oldest first as the thread reads, each under a quiet divider
// saying when and where it happened. Read only: no keeping a line, no reply. At the top, a way to ask for older ones.
import { Fragment } from 'preact';
import type { PastConversation, PastSummary, PastTurn } from '../../api/types';
import { person } from '../../session/session';
import { moment } from '../memory/facts';
import { HouseholdLine } from './HouseholdLine';
import { LineText } from './Markdown';
import { Paste } from './Paste';
import { chatEarlier, type EarlierStream } from './past';
import { when, where } from './where';

export function Divider({ at, channel, place }: { at: string; channel: PastSummary['channel']; place: string | null }) {
  const label = where(channel, place);
  return (
    <div class="past-divider" role="separator">
      <span>{when(at)} · {label ?? <span class="unk">not recorded</span>}</span>
    </div>
  );
}

function Spoke({ turn, mine }: { turn: PastTurn; mine: string }) {
  const hers = turn.author === 'ashley';
  const who = turn.speaker ?? 'Someone';
  return (
    <div id={`turn-${turn.id}`} class={`m past ${hers ? 'her' : 'you'}`}>
      {hers ? <span class="her-gap" /> : <span class="who you sm" aria-hidden="true">{(turn.speaker ?? '?').slice(0, 1)}</span>}
      <div>
        <div class={`meta${hers ? ' her-meta' : ''}`}>
          {hers ? 'Ashley' : turn.speaker === mine ? mine : who} · {moment(turn.at)}
        </div>
        <LineText hers={hers} text={turn.text} />
        {turn.attachment && <Paste attachment={turn.attachment} />}
      </div>
    </div>
  );
}

export function Earlier({ open, more, stream = chatEarlier }: { open: number | null; more: () => void; stream?: EarlierStream }) {
  const { earlier, earlierMore, earlierState } = stream;
  const loaded = earlier.value;
  const state = earlierState.value;
  const mine = person.value?.name ?? '';
  return (
    <>
      {state === 'failed' && (
        <p class="past-note meta" role="alert">
          Couldn't load anything further back. <button class="linkish" type="button" onClick={more}>Try again</button>
        </p>
      )}
      {state === 'loading' && <p class="past-note meta">Reading further back…</p>}
      {state === 'idle' && earlierMore.value && (
        <p class="past-note meta"><button class="linkish" type="button" onClick={more}>Further back</button></p>
      )}
      {[...loaded].reverse().filter((c: PastConversation) => c.id !== open).map((c) => (
        <Fragment key={c.id}>
          <Divider at={c.started_at} channel={c.channel} place={c.place} />
          {c.lines.map((t) => t.author === 'household'
            ? <HouseholdLine key={t.id} id={t.id} name={t.speaker} text={t.text} at={t.at} />
            : <Spoke key={t.id} turn={t} mine={mine} />)}
        </Fragment>
      ))}
    </>
  );
}
