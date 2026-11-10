// The conversation's lines, oldest first: the person's on the right in blue, hers on the left in brass, each with
// who and when. A line of theirs she gave no reply to says why; while she works on one, a line of hers says so. A
// stored line can be carried to Memory, or kept with its "Remember" action; Memory shows what became of it.
import { useCallback, useRef } from 'preact/hooks';
import { flyInto, ghostOf } from '../../shell/carry';
import { moment } from '../memory/facts';
import { useCarryLine } from './carryLine';
import type { Line, Missed } from './chat';
import { HouseholdLine } from './HouseholdLine';
import { KeepButton } from './KeepButton';
import { LineText } from './Markdown';
import { Paste } from './Paste';
import { Fold } from './Fold';
import { RunDetails } from './RunDetails';
import { AgreeButton } from './AgreeButton';
import { Agreed, Held } from './Receipts';
import { canKeep, keep } from './remember';
import { VoiceMark } from '../../speech/VoiceMark';

const MISSED: Record<Missed, string> = {
  refused: 'She declined to answer that.',
  unreachable: "Can't reach her. No reply.",
  failed: "That didn't go through. No reply.",
  stalled: "She didn't finish that one. Try sending it again.",
  retrying: "Couldn't finish that. Trying again.",
  unfinished: "Couldn't finish that.",
  too_big: 'That was too big to do in one go. Try asking for a smaller part.',
};

/** Missed states that are a status, not a failed send: a quiet line beside the message, as a receipt is. */
const STATUS: ReadonlySet<Missed> = new Set<Missed>(['retrying', 'unfinished', 'too_big']);

/** Where the rest of her reply was said: a quiet link line the page words itself, never a line of hers. */
function ContinuedOn({ bench, title, turn }: { bench: number; title: string; turn: number | undefined }) {
  return (
    <p class="receipt receipt-done" id={turn === undefined ? undefined : `turn-${turn}`}>
      <a class="continued" href={`/workshop/${bench}`}><span aria-hidden="true">{'\u2192'}</span> Continued on bench {'\u201C'}{title}{'\u201D'}</a>
    </p>
  );
}

function Said({ line, name, conversation }: { line: Line; name: string; conversation: number | null }) {
  const hers = line.author === 'ashley';
  const row = useRef<HTMLDivElement>(null);
  const turn = line.turn;
  const keepable = conversation !== null && turn !== undefined;
  const drop = useCallback(() => {
    if (conversation !== null && turn !== undefined) void keep(conversation, turn);
  }, [conversation, turn]);
  useCarryLine(row, keepable && canKeep(turn), drop);
  const remember = () => {
    if (!row.current || !keepable || !canKeep(turn)) return;
    void flyInto(ghostOf(row.current), 'memory');
    drop();
  };
  if (line.continuedOn !== undefined) return <ContinuedOn bench={line.continuedOn} title={line.text} turn={turn} />;
  return (
    <div ref={row} id={turn === undefined ? undefined : `turn-${turn}`} class={`m ${hers ? 'her' : 'you'}${line.missed ? ' missed' : ''}${keepable && canKeep(turn) ? ' keepable' : ''}`}>
      {hers ? <span class="her-gap" /> : <span class="who you sm" aria-hidden="true">{name.slice(0, 1)}</span>}
      <div>
        <div class={`meta${hers ? ' her-meta' : ''}`}>
          {hers ? 'Ashley' : name} · {moment(line.at)}
          {keepable && canKeep(turn) && <KeepButton remember={remember} />}
        </div>
        <LineText hers={hers} text={line.text} />
        {hers && turn !== undefined && <VoiceMark turn={turn} />}
        {hers && line.receipts && <Held receipts={line.receipts} agree={line.agree} />}
        {hers && !line.receipts && line.agree !== undefined && <AgreeButton proposal={line.agree} />}
        {!hers && line.agreed && <Agreed agreed={line.agreed} />}
        {line.attachment && <Paste attachment={line.attachment} />}
        {line.runs?.map((r) => <RunDetails key={r.id} run={r} />)}
        {hers && <Fold receipts={line.receipts} looks={line.looks} />}
        {line.missed && (STATUS.has(line.missed)
          ? <p class="receipt receipt-done" role="status">{MISSED[line.missed]}</p>
          : <div class="m-err" role="alert">{MISSED[line.missed]}</div>)}
      </div>
    </div>
  );
}

function Thinking() {
  return (
    <div class="m her thinking" aria-label="Ashley is thinking">
      <span class="her-gap" />
      <div>
        <div class="meta her-meta">Ashley</div>
        <p class="dots" aria-hidden="true"><i /><i /><i /></p>
      </div>
    </div>
  );
}

/** `conversation` is the open conversation the lines are of, which a stored line is remembered from; null when none. */
export function Thread({ lines, name, thinking, conversation }: {
  lines: readonly Line[]; name: string; thinking: boolean; conversation: number | null;
}) {
  if (!lines.length && !thinking) return null;
  return (
    <>
      {lines.map((l) => l.author === 'household'
        ? <HouseholdLine key={l.key} id={l.turn} text={l.text} at={l.at} />
        : <Said key={l.key} line={l} name={name} conversation={conversation} />)}
      {thinking && <Thinking />}
    </>
  );
}
