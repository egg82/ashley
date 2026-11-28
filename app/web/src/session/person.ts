// What the person part reads, as a signed-in person's session has it: the Memory room's facts and voiceprints, read
// without the room's shell state, so a card in a column never marks her room unreachable.
import { computed, signal } from '@preact/signals';
import { ApiError, getFacts } from '../api/client';
import type { PersonSource } from '../components/parts/sources';
import { facts } from '../rooms/memory/memory';
import { loadPrints, prints, printsState } from '../rooms/memory/voice';
import { load as reloadSession } from './session';

const factsState = signal<'loading' | 'ready' | 'failed'>('loading');

async function readFacts(): Promise<void> {
  try {
    facts.value = (await getFacts()).items;
    factsState.value = 'ready';
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) void reloadSession();
    factsState.value = 'failed';
  }
}

export const personSource: PersonSource = {
  facts: computed(() => (factsState.value === 'ready' ? facts.value : factsState.value === 'loading' ? undefined : null)),
  prints: computed(() => (printsState.value === 'ready' ? prints.value : printsState.value === 'loading' ? undefined : null)),
  async read() {
    await Promise.all([readFacts(), loadPrints()]);
  },
};
