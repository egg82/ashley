// What the connections room holds: the person's accounts as last read, whether they could be read, and the two changes a
// person can make to their Discord link. Every change goes through here.
import { signal } from '@preact/signals';
import { ApiError, getAccounts, startDiscordLink, unlinkAccount } from '../../api/client';
import type { LinkedAccount } from '../../api/types';
import { load as reloadSession } from '../../session/session';
import { herRoomLeft, roomReached } from '../../shell/her/state';

/** `unreachable`: a 503 or no answer at all; `failed`: any other error. */
export type Load = 'loading' | 'ready' | 'unreachable' | 'failed';
/** Where a link came back to, as the server's callback names it in `?link=`. */
export type Outcome = 'linked' | 'cancelled' | 'taken' | 'wrong_person' | 'unavailable' | 'failed';
const OUTCOMES: readonly Outcome[] = ['linked', 'cancelled', 'taken', 'wrong_person', 'unavailable', 'failed'];

export const accounts = signal<LinkedAccount[]>([]);
/** Whether linking Discord is set up here; the server says so with the list. */
export const canLink = signal(false);
export const loadState = signal<Load>('loading');
/** True from asking for a link until the browser leaves for Discord. */
export const leaving = signal(false);
/** What the last change or the link's return came to; null when there is nothing to say. */
export const said = signal<Outcome | 'unlinked' | 'unlink_failed' | 'unreachable' | 'start_failed' | null>(null);

export function outcomeOf(raw: string | undefined): Outcome | null {
  return OUTCOMES.find((o) => o === raw) ?? null;
}

function unreachable(error: unknown): boolean {
  if (error instanceof ApiError && error.status === 401) void reloadSession();
  return !(error instanceof ApiError) || error.status === 503;
}

function setLoad(state: Load): void {
  loadState.value = state;
  roomReached(state !== 'unreachable');
}

export async function loadAccounts(): Promise<void> {
  setLoad('loading');
  try {
    const answer = await getAccounts();
    accounts.value = answer.accounts;
    canLink.value = answer.discord_linking;
    setLoad('ready');
  } catch (error) {
    setLoad(unreachable(error) ? 'unreachable' : 'failed');
  }
}

/** The room is left: her state stops answering for it. */
export function leaveRoom(): void {
  herRoomLeft();
}

/** Asks for a link and sends this browser to Discord, which returns it to `/connections?link=<outcome>`. */
export async function linkDiscord(): Promise<void> {
  leaving.value = true;
  said.value = null;
  try {
    const { authorize_url } = await startDiscordLink();
    window.location.assign(authorize_url);
  } catch (error) {
    leaving.value = false;
    said.value = unreachable(error) ? 'unreachable' : 'start_failed';
  }
}

export async function unlink(id: number): Promise<void> {
  try {
    await unlinkAccount(id);
    accounts.value = accounts.value.filter((a) => a.id !== id);
    said.value = 'unlinked';
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      accounts.value = accounts.value.filter((a) => a.id !== id);
      said.value = 'unlinked';
      return;
    }
    said.value = unreachable(error) ? 'unreachable' : 'unlink_failed';
  }
}
