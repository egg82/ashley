// The facts a signed-in person may read, as the fact cards beside her words read them (`GET /api/memory/facts`): read
// when a card first shows and again on a turn on any thread, since a new turn can cite a fact learned since.
import { signal } from '@preact/signals';
import { ApiError, getFacts } from '../api/client';
import type { MemoryFact } from '../api/types';
import type { FactSource } from '../components/parts/sources';
import { onThreadTurn } from './live';
import { load as reloadSession } from './session';

const facts = signal<readonly MemoryFact[] | null | undefined>(undefined);
let watchers = 0;
let stop: (() => void) | null = null;

async function read(): Promise<void> {
  try {
    facts.value = (await getFacts()).items;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) void reloadSession();
    else facts.value = null;
  }
}

export const householdFacts: FactSource = {
  facts,
  watch() {
    watchers += 1;
    if (!stop) {
      void read();
      stop = onThreadTurn(() => void read());
    }
    return () => {
      watchers -= 1;
      if (watchers === 0 && stop) {
        stop();
        stop = null;
      }
    };
  },
};
