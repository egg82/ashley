// The lines a conversation shows: the stored ones with what only one page knows laid over their end.
import type { ChatAttachment, ChatConversationTurn, ChatLook, ChatRun, WireAgreed, WireReceipts } from '../../api/types';
import { answered, owedAt, stillOn } from './owed.ts';

/** Why a message of the person's got no reply. */
export type Missed = 'refused' | 'unreachable' | 'failed' | 'stalled' | 'retrying' | 'unfinished' | 'too_big';

/** What a turn's `why` (`TurnFailedWhy`) marks the line owed an answer as. */
export function missedFor(why: 'unavailable' | 'refused' | 'retrying' | 'unfinished' | 'too_big'): Missed {
  return why === 'unavailable' ? 'unreachable' : why;
}

export interface Line {
  key: string;
  author: 'person' | 'ashley' | 'household';
  text: string;
  at: string;
  /** The stored turn's id; unset on a line only this page knows yet, which cannot be remembered. */
  turn?: number;
  /** Set on the person's line when it got no reply. */
  missed?: Missed;
  /** Set on her line that went out while her answer was still to come; the answer is a later line. */
  follows?: boolean;
  /** The scripts she ran for this answer, in order; set on a stored answer of hers. */
  runs?: readonly ChatRun[];
  /** The pictures of a bench she was given for this answer, in order; set on a stored answer of hers. */
  looks?: readonly ChatLook[];
  /** Set on the person's line while her work on it is in flight: pending, not missed. */
  working?: boolean;
  /** Set on a line of hers that hands the reader on to a bench, by its id: the rest of her reply was said there, and
   * `text` labels the link. */
  continuedOn?: number;
  /** Set on her answer whose held calls can still be agreed to: the held proposal's id (`ChatConversationTurn.agree`). */
  agree?: number;
  /** What code showed beside her words on this answer: the changes that ran and the calls waiting (`ChatConversationTurn.receipts`). */
  receipts?: WireReceipts;
  /** What became of the held calls the person's agreeing line carried out (`ChatConversationTurn.agreed`), shown beside it. */
  agreed?: WireAgreed;
  /** What the person pasted with this line, shown folded under it. */
  attachment?: ChatAttachment;
}

/** A stored turn as the line it shows. */
export function storedLine(t: ChatConversationTurn): Line {
  return { key: `t${t.id}`, author: t.author, text: t.text, at: t.at, turn: t.id, follows: t.follows, runs: t.runs, looks: t.looks, working: t.working, continuedOn: t.continued_on ?? undefined, attachment: t.attachment ?? undefined, agree: t.agree ?? undefined, receipts: t.receipts ?? undefined, agreed: t.agreed ?? undefined };
}

/** Whether one of the last `within` lines says what `one` says. */
function among(lines: readonly Line[], one: Line, within: number): boolean {
  return lines.slice(-within).some((l) => l.author === one.author && l.text === one.text);
}

/** What only a page knows about a conversation, laid over the stored one until a read-back has it. */
export interface Overlay {
  failed: Line | null;
  mine: Line | null;
  hers: { line: Line; held: boolean } | null;
}

/** The lines shown: the stored conversation, with what only this page knows laid over its end. */
export function overlaid(stored: readonly Line[], { failed, mine, hers }: Overlay): readonly Line[] {
  const out = [...stored];
  const owed = owedAt(out);
  // A failed send is marked where it is still owed, unless she is still working on it (a turn resumed on another pod
  // may answer it after all); she declining it is final.
  if (failed && owed >= 0 && out[owed]!.text === failed.text) {
    if (!out[owed]!.working || failed.missed === 'refused' || failed.missed === 'retrying') out[owed] = { ...out[owed]!, missed: failed.missed };
  } else if (failed && !answered(out, failed.text)) out.push(failed);
  if (mine && !among(out, mine, 2)) out.push(mine);
  // A held reply with no words is pending: her turn is being worked on elsewhere, and she shows thinking until it lands.
  if (hers?.held && hers.line.text && out.at(-1)?.author === 'person') out.push(hers.line);
  else if (hers && !hers.held && !among(out, hers.line, 1)) out.push(hers.line);
  return out;
}


/** Whether her thinking belongs under `lines`: she is working on the turn she is answering (the server says so), or she
 * is `thinking` and a message here, the person's or the household's (a turn the server started), is unanswered, not
 * only a turn on another channel. */
export function awaiting(lines: readonly Line[], sending: boolean, thinking: boolean): boolean {
  if (stillOn(lines)) return true;
  const last = lines.at(-1);
  const owed = last?.author === 'ashley' && last.follows === true;
  return thinking && (sending || owed || (last?.author !== 'ashley' && last !== undefined && !last.missed));
}

/** What a turn that has no reply shows: the person's line still owed an answer, marked as `why` says, or nothing when
 * none is owed. */
export function failedLine(shown: readonly Line[], why: Parameters<typeof missedFor>[0]): Line | null {
  const owed = shown[owedAt(shown)];
  return owed ? { ...owed, missed: missedFor(why) } : null;
}
