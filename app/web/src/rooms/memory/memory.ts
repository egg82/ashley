// What the memory room holds: the facts as last read, whether they could be read, and the two changes a person can
// make. Every change goes through here, so a card never edits the list itself.
import { signal } from '@preact/signals';
import { ApiError, correctFact, forgetFact, getFacts, moveFact } from '../../api/client';
import type { MemoryFact } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import { herRoomLeft, roomReached } from '../../shell/her/state';

/** `unreachable`: a 503 or no answer at all; `failed`: any other error. */
export type Load = 'loading' | 'ready' | 'unreachable' | 'failed';
/** How a change ended. `gone`: the fact was no longer hers to change (404), and its card has been removed. */
export type Outcome = 'ok' | 'gone' | 'unreachable' | 'failed';

export interface Note {
  text: string;
  /** A note about something forgotten wears forgetting's red edge. */
  forgot: boolean;
}

export const facts = signal<MemoryFact[]>([]);
export const loadState = signal<Load>('loading');
/** Ids of facts that replaced another in this visit; their cards play the supersede. */
export const corrected = signal<ReadonlySet<number>>(new Set());
/** The one fact whose source the rail shows; null shows the newest. */
export const selected = signal<number | null>(null);
export const note = signal<Note | null>(null);

function outcomeOf(error: unknown): Outcome {
  if (error instanceof ApiError) {
    if (error.status === 401) void reloadSession();
    if (error.status === 404) return 'gone';
    if (error.status === 503) return 'unreachable';
    return 'failed';
  }
  return 'unreachable';
}

function setLoad(state: Load): void {
  loadState.value = state;
  roomReached(state !== 'unreachable');
}

export async function loadFacts(): Promise<void> {
  setLoad('loading');
  try {
    facts.value = (await getFacts()).items;
    setLoad('ready');
  } catch (error) {
    const outcome = outcomeOf(error);
    setLoad(outcome === 'unreachable' ? 'unreachable' : 'failed');
  }
}

/** The room is left: her state stops answering for it. */
export function leaveRoom(): void {
  herRoomLeft();
}

export function remove(id: number): void {
  facts.value = facts.value.filter((f) => f.id !== id);
}

function dropStale(id: number): void {
  remove(id);
  note.value = { text: 'That fact had already changed or been forgotten.', forgot: false };
}

/** Replaces fact `id` where it stands with the fact the server answers. */
export async function correct(id: number, text: string): Promise<Outcome> {
  try {
    const next = await correctFact(id, { text });
    facts.value = facts.value.map((f) => (f.id === id ? next : f));
    corrected.value = new Set([...corrected.value, next.id]);
    if (selected.value === id) selected.value = next.id;
    return 'ok';
  } catch (error) {
    const outcome = outcomeOf(error);
    if (outcome === 'gone') dropStale(id);
    return outcome;
  }
}

const MOVED = { household: "Now the household's.", mine: 'Now yours.' } as const;

/** Makes fact `id` the household's or the signed-in person's, replacing it where it stands with the answer. */
export async function move(id: number, to: 'household' | 'mine'): Promise<Outcome> {
  try {
    const next = await moveFact(id, { to });
    facts.value = facts.value.map((f) => (f.id === id ? next : f));
    corrected.value = new Set([...corrected.value, next.id]);
    if (selected.value === id) selected.value = next.id;
    note.value = { text: MOVED[to], forgot: false };
    return 'ok';
  } catch (error) {
    const outcome = outcomeOf(error);
    if (outcome === 'gone') dropStale(id);
    return outcome;
  }
}

/** Deletes fact `id` for good. The caller removes the card once its collapse has played. */
export async function forget(id: number): Promise<Outcome> {
  try {
    await forgetFact(id);
    note.value = { text: "Forgotten for good, with its history. She can't get it back.", forgot: true };
    return 'ok';
  } catch (error) {
    const outcome = outcomeOf(error);
    if (outcome === 'gone') dropStale(id);
    return outcome;
  }
}
