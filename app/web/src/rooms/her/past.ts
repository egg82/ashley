// The person's earlier conversations, read back a page at a time as they scroll up past the open one. Each is fetched
// whole by id after its page lists it; they are read only, and nothing here touches the open conversation. A stream
// reads one source of pages: her room's is the person's own history, a bench's is the conversations on its thread.
import { signal } from '@preact/signals';
import { getPast, getPastPage } from '../../api/client';
import type { PastConversation, PastHistory } from '../../api/types';

export type EarlierState = 'idle' | 'loading' | 'failed';

/** Reads `limit` conversations' summaries newest first, after the `before` an earlier page returned. */
export type PageSource = (limit: number, before: string | null) => Promise<PastHistory>;

/** Conversations per page: each is a request of its own, so a page is small. */
const PAGE = 3;

export function earlierStream(source: PageSource) {
  /** Loaded earlier conversations, newest first (the order the server pages in). */
  const earlier = signal<readonly PastConversation[]>([]);
  const earlierState = signal<EarlierState>('idle');
  /** Whether the server has more to give past the last page loaded. */
  const earlierMore = signal(true);
  let next: string | null = null;
  let generation = 0;

  /** Forgets everything loaded; the room being entered starts from the newest again. */
  function earlierReset(): void {
    generation++;
    earlier.value = [];
    earlierState.value = 'idle';
    earlierMore.value = true;
    next = null;
  }

  /** Loads the next page of earlier conversations, skipping the one `open` names. Does nothing while loading or at the end. */
  async function loadEarlier(open: number | null): Promise<void> {
    if (earlierState.value === 'loading' || !earlierMore.value) return;
    const mine = generation;
    earlierState.value = 'loading';
    try {
      const page = await source(PAGE, next);
      const wanted = page.conversations.filter((c) => c.id !== open);
      const got = await Promise.all(wanted.map((c) => getPast(c.id)));
      if (mine !== generation) return;
      next = page.next;
      earlierMore.value = page.next !== null;
      earlier.value = [...earlier.value, ...got];
      earlierState.value = 'idle';
    } catch {
      if (mine === generation) earlierState.value = 'failed';
    }
  }

  return { earlier, earlierState, earlierMore, earlierReset, loadEarlier };
}

export type EarlierStream = ReturnType<typeof earlierStream>;

/** Her room's: the person's own conversations on any channel. */
export const chatEarlier = earlierStream(getPastPage);
export const { earlier, earlierState, earlierMore, earlierReset, loadEarlier } = chatEarlier;
