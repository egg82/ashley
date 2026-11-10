// The kiosk's live feed, `GET /api/kiosk/live`, seen as the device (`session/feed.ts` keeps it open): her state in any
// shared turn drives her mark (`liveMark`), a turn stored on the device's thread and "something may have been missed"
// go to the callbacks `startLive` is given, which read the conversation back, and a change to a screen goes to `listenScreen`'s. While it is down, `liveUp` is false and
// the page looks for itself on its slow timers.
import type { TurnFailedWhy } from '../session/live';
import { computed, signal } from '@preact/signals';
import { kioskLiveFeed } from '../api/client';
import type { MarkState } from '../components/AshleyMark';
import { createFeed } from '../session/feed';

type Doing = 'listening' | 'thinking' | 'speaking';

/** Turns the feed reported that are not over, by token, and when to stop believing each (its end can be lost with the
 * server that ran it). */
const turns = signal<ReadonlyMap<string, { state: Doing; timer: ReturnType<typeof setTimeout> }>>(new Map());
let readTurn: () => void = () => undefined;
let readAll: () => void = () => undefined;
let turnFailed: (why: TurnFailedWhy) => void = () => undefined;
let screenChanged: (device: number) => void = () => undefined;

function hear(turn: string, state: Doing | 'idle', atMostMs: number): void {
  const next = new Map(turns.value);
  clearTimeout(next.get(turn)?.timer);
  next.delete(turn);
  if (state !== 'idle') next.set(turn, { state, timer: setTimeout(() => hear(turn, 'idle', 0), atMostMs) });
  turns.value = next;
}

function forget(): void {
  turns.value.forEach((t) => clearTimeout(t.timer));
  turns.value = new Map();
}

const feed = createFeed(kioskLiveFeed, {
  heard(event) {
    if (event.type === 'state') hear(event.turn, event.state, event.at_most_s * 1000);
    else if (event.type === 'failed') turnFailed(event.why);
    else if (event.type === 'screen') screenChanged(event.device_id);
    else readTurn();
  },
  resync() {
    forget();
    readAll();
  },
  lost: forget,
});

/** Whether the feed is open. */
export const liveUp = feed.up;

/** What the feed says she is doing: speaking over thinking over listening, idle when no turn is going. */
export const liveMark = computed<MarkState>(() => {
  const states = [...turns.value.values()].map((t) => t.state);
  for (const doing of ['speaking', 'thinking', 'listening'] as const) if (states.includes(doing)) return doing;
  return 'idle';
});

/** Calls `heard` with the device each time a screen of the household changes; the last listener is the one kept. */
export function listenScreen(heard: (device: number) => void): void {
  screenChanged = heard;
}

/** Opens the feed: `onTurn` when a turn is stored on this device's thread, `onFailed` when one there ended with no
 * reply after its request returned pending, `onResync` whenever anything may have been missed. Returns the stop. */
export function startLive(onTurn: () => void, onResync: () => void,
                          onFailed: (why: TurnFailedWhy) => void): () => void {
  readTurn = onTurn;
  turnFailed = onFailed;
  readAll = onResync;
  feed.open();
  return () => {
    feed.close();
    forget();
  };
}
