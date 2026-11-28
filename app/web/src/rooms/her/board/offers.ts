// What a board row offers, by the item's kind and state: pure, so it is tested without a page. A proposal is agreed by a
// tap when it holds calls (`can_tap`), else by answering her in the conversation it was made in; a live watch can be
// paused or cancelled and a paused one resumed or cancelled; something she did on her own can be undone only while the server offers it (`can_undo`).
import type { ActionUndone, UndoDone, WorkItem } from '../../../api/types';

type UndoHow = ActionUndone['how'];

export type Offer =
  | { kind: 'agree'; proposal: number }
  | { kind: 'reply'; here: boolean }
  | { kind: 'pause'; watch: number }
  | { kind: 'resume'; watch: number }
  | { kind: 'cancel'; watch: number }
  | { kind: 'undo'; action: number };

/** The actions row `item` offers; `open` is the conversation open on this screen, where a reply can be typed. */
export function offers(item: WorkItem, open: number | null): Offer[] {
  if (item.kind === 'proposal') {
    if (item.can_tap) return [{ kind: 'agree', proposal: item.id }];
    if (item.conversation_id != null) return [{ kind: 'reply', here: item.conversation_id === open }];
    return [];
  }
  if (item.kind === 'watch' && (item.state === 'running' || item.state === 'stopped')) {
    return [{ kind: 'pause', watch: item.id }, { kind: 'cancel', watch: item.id }];
  }
  if (item.kind === 'watch' && item.state === 'paused') return [{ kind: 'resume', watch: item.id }, { kind: 'cancel', watch: item.id }];
  if (item.kind === 'action' && item.can_undo === true && !item.undone) return [{ kind: 'undo', action: item.id }];
  return [];
}

const UNDONE: Record<UndoHow, string> = {
  undoing: 'Undoing…',
  undone: 'Undone',
  waiting_on_you: 'Undo waits on your yes',
  gone: 'Already gone, nothing undone',
};

/** How a taken Undo stands, in words, or null when it was never taken. */
export function undoneWord(item: WorkItem): string | null {
  return item.undone ? UNDONE[item.undone.how] ?? null : null;
}

/** What an Undo the person just pressed did, in words. */
export function undoResult(how: UndoDone['how']): string {
  if (how === 'waiting_on_you') return 'Taking it back is a delete, so it waits on your yes. Reply to her to agree.';
  return UNDONE[how];
}

const REFUSED: Record<string, string> = {
  no_undo: "This can't be undone.",
  already_undone: 'Already undone.',
  refused: "She couldn't undo it.",
};

/** Why a board action did not go through, from its status and refusal code. */
export function whyNot(status: number | undefined, code: string | undefined): string {
  const refused = code === undefined ? undefined : REFUSED[code];
  if (status === 409 && refused) return refused;
  if (status === 404) return "It's no longer there.";
  if (status === 429) return 'Too many at once. Wait a moment.';
  if (status === undefined || status === 503) return "Couldn't reach her. Try again.";
  return "That didn't work. Try again.";
}
