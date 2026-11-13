// Asking her to remember a line of the open conversation. She thinks while the decision runs (`herRemembering`); what
// came of it is a short note by the Memory bearing, where the line was sent, and is kept nowhere: Memory shows the
// facts, and a result that lands after the room was left is dropped.
import { signal } from '@preact/signals';
import { ApiError, rememberTurn } from '../../api/client';
import type { RememberResponse } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import { herRemembered, herRemembering } from '../../shell/her/state';
import { acknowledge } from '../../shell/carry';

const DONE_MS = 3200;
const FAILED_MS = 6000;

/** The lines asked about whose answer is still out, by turn id. */
const asking = signal<ReadonlySet<number>>(new Set());

let generation = 0;

function setAsking(turn: number, on: boolean): void {
  const next = new Set(asking.value);
  if (on) next.add(turn);
  else next.delete(turn);
  asking.value = next;
}

function whyNot(error: unknown): string {
  if (!(error instanceof ApiError)) return "Can't reach Ashley, so nothing was remembered. Try again.";
  if (error.status === 401) void reloadSession();
  if (error.status === 503) return "Can't reach Ashley, so nothing was remembered. Try again.";
  if (error.status === 422) return "She couldn't make anything of that line. Nothing changed.";
  return error.status === 404 ? 'That line is gone, so nothing was remembered.' : "Couldn't remember that. Nothing changed. Try again.";
}

function saidOf(got: RememberResponse): string {
  if (got.facts.length) return got.facts.length > 1 ? `${got.facts.length} facts in Memory` : 'In Memory';
  if (got.ended) return 'Memory updated';
  return got.unseen ? 'Kept for someone else' : 'Nothing new to remember';
}

/** Whether `turn` can be asked about now: not while its last ask is still out. */
export function canKeep(turn: number): boolean {
  return !asking.value.has(turn);
}

/** Asks her to remember turn `turn` of conversation `conversation`. */
export async function keep(conversation: number, turn: number): Promise<void> {
  if (!canKeep(turn)) return;
  const here = generation;
  setAsking(turn, true);
  herRemembering();
  try {
    const got = await rememberTurn({ conversation_id: conversation, turn_id: turn });
    if (here === generation) acknowledge('memory', saidOf(got), DONE_MS);
  } catch (error) {
    if (here === generation) acknowledge('memory', whyNot(error), FAILED_MS, true);
  } finally {
    if (here === generation) {
      setAsking(turn, false);
      herRemembered();
    }
  }
}

/** The room was entered or left: nothing asked before is shown or waited for. */
export function keptReset(): void {
  generation++;
  asking.value = new Set();
}
