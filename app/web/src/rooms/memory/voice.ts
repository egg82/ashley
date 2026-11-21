// What the Your voice tab holds: the signed-in person's voiceprints as last read, whether they could be read, and
// forgetting them all. Every change goes through here, so the tab never edits the list itself.
import { signal } from '@preact/signals';
import { ApiError, forgetVoiceprints, getVoiceprints } from '../../api/client';
import type { Voiceprint } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import type { Load, Outcome } from './memory';
import { note } from './memory';

export const prints = signal<Voiceprint[]>([]);
export const printsState = signal<Load>('loading');

function outcomeOf(error: unknown): Outcome {
  if (error instanceof ApiError) {
    if (error.status === 401) void reloadSession();
    return error.status === 503 ? 'unreachable' : 'failed';
  }
  return 'unreachable';
}

export async function loadPrints(): Promise<void> {
  printsState.value = 'loading';
  try {
    prints.value = (await getVoiceprints()).prints;
    printsState.value = 'ready';
  } catch (error) {
    printsState.value = outcomeOf(error) === 'unreachable' ? 'unreachable' : 'failed';
  }
}

/** Forgets every print of the signed-in person and empties the list. */
export async function forgetPrints(): Promise<Outcome> {
  try {
    await forgetVoiceprints();
  } catch (error) {
    return outcomeOf(error);
  }
  prints.value = [];
  note.value = { text: 'Done. She no longer knows your voice.', forgot: true };
  return 'ok';
}
