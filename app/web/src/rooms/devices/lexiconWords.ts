// The household's pronunciation words as last read, and what the last edit came to.
import { signal } from '@preact/signals';
import { ApiError, deleteLexiconWord, getLexicon, putLexiconWord } from '../../api/client';
import type { LexiconRefused, LexiconWord } from '../../api/types';

export type LexiconLoad = 'loading' | 'ready' | 'failed';

export const words = signal<LexiconWord[]>([]);
export const limit = signal(0);
export const lexiconState = signal<LexiconLoad>('loading');
/** What the last edit came to; null when there is nothing to say. */
export const lexiconSaid = signal<LexiconRefused['refused_for'] | 'failed' | null>(null);

export async function loadLexicon(): Promise<void> {
  lexiconState.value = 'loading';
  try {
    const found = await getLexicon();
    words.value = found.words;
    limit.value = found.limit;
    lexiconState.value = 'ready';
  } catch {
    lexiconState.value = 'failed';
  }
}

/** Sets the spelling for `real`; whether it was stored. */
export async function setWord(real: string, spoken: string): Promise<boolean> {
  lexiconSaid.value = null;
  try {
    const got = await putLexiconWord(real, spoken);
    if ('refused_for' in got) {
      lexiconSaid.value = got.refused_for;
      return false;
    }
  } catch {
    lexiconSaid.value = 'failed';
    return false;
  }
  await loadLexicon();
  return true;
}

export async function removeWord(real: string): Promise<void> {
  lexiconSaid.value = null;
  try {
    await deleteLexiconWord(real);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) lexiconSaid.value = 'failed';
  }
  await loadLexicon();
}
