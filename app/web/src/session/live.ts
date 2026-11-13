// The one owner of the person's live feed, `GET /api/live`: open while a person is signed in, reopened with backoff when
// it drops (`feed.ts`). Her state goes to `shell/her/state.ts` and her moving the page to `shell/her/moves.ts`; a turn
// on one of the person's threads, a change to one of their benches, a change to a screen of the household, and "read back what you show" (the feed opened, or
// may have missed something), and her cue of a video piece's player, go to whoever listens. While it is down, `liveUp`
// is false and a room that shows something live looks for itself.
import { liveFeed } from '../api/client';
import { reportVisibility } from '../api/screens';
import { benchChangedBy, herMoved } from '../shell/her/moves';
import { herLive, herLiveLost } from '../shell/her/state';
import type { Cue } from '../rooms/workshop/pieces/player';
import { createFeed } from './feed';
import { createReporting, screenToken } from './screen';

const threadTurns = new Set<(thread: string) => void>();
const threadFailures = new Set<(thread: string, why: TurnFailedWhy) => void>();
const benchChanges = new Set<(bench: number, seq: number) => void>();
const screenChanges = new Set<(device: number, seq: number) => void>();
const benchCues = new Set<(bench: number, piece: number, cue: Cue, by: CueBy) => void>();
const resyncs = new Set<() => void>();

const feed = createFeed(() => liveFeed(screenToken), {
  heard(event) {
    if (event.type === 'state') herLive(event.turn, event.state, event.at_most_s * 1000);
    else if (event.type === 'turn') threadTurns.forEach((h) => h(event.thread));
    else if (event.type === 'failed') threadFailures.forEach((h) => h(event.thread, event.why));
    else if (event.type === 'bench') {
      benchChanges.forEach((h) => h(event.bench_id, event.seq));
      benchChangedBy(event.bench_id, event.by);
    }
    else if (event.type === 'screen') screenChanges.forEach((h) => h(event.device_id, event.seq));
    else if (event.type === 'cue') benchCues.forEach((h) => h(event.bench_id, event.piece_id, event, 'her'));
    else if (event.type === 'page') herMoved(event.room, event.bench_id ?? null);
  },
  resync() {
    herLiveLost();
    resyncs.forEach((readBack) => readBack());
  },
  lost: herLiveLost,
});

/** Whether the feed is open; while it is not, nothing it would have said is heard. */
export const liveUp = feed.up;
const reporting = createReporting(feed.up, (visible) => reportVisibility(screenToken, visible));

/** Opens the feed, unless it is open or opening, and reports whether the page is in the foreground while it is up. */
export function openLive(): void {
  feed.open();
  reporting.start();
}

/** Closes the feed and stops reopening it (signed out). */
export function closeLive(): void {
  reporting.stop();
  feed.close();
}

/** Calls `heard` with the thread each time one of the person's threads gets a turn; returns the unsubscribe. */
export function onThreadTurn(heard: (thread: string) => void): () => void {
  threadTurns.add(heard);
  return () => threadTurns.delete(heard);
}

/** Why a turn on one of the person's threads ended with no reply after its request returned pending. */
export type TurnFailedWhy = 'unavailable' | 'refused' | 'retrying' | 'unfinished' | 'too_big';

/** Calls `heard` with the thread and why each time a turn there ends with no reply after its request had returned
 * pending; returns the unsubscribe. */
export function onTurnFailed(heard: (thread: string, why: TurnFailedWhy) => void): () => void {
  threadFailures.add(heard);
  return () => threadFailures.delete(heard);
}

/** Calls `heard` with the bench and the command's `seq` each time one of the person's benches changes; returns the
 * unsubscribe. */
export function onBenchChanged(heard: (bench: number, seq: number) => void): () => void {
  benchChanges.add(heard);
  return () => benchChanges.delete(heard);
}

/** Calls `heard` with the device and the command's `seq` each time a screen of the household changes (its layout or its
 * buttons); returns the unsubscribe. */
export function onScreenChanged(heard: (device: number, seq: number) => void): () => void {
  screenChanges.add(heard);
  return () => screenChanges.delete(heard);
}

/** Who cued a player: she did, over the feed, or the person did, on this page (`cueBenchPlayer`). */
export type CueBy = 'her' | 'person';

/** Calls `heard` with the bench, the piece, the cue and who gave it each time she cues a player on one of the person's
 * benches, or the person does on this page; returns the unsubscribe. A screen that was not listening when the cue came
 * never hears it. */
export function onBenchCue(heard: (bench: number, piece: number, cue: Cue, by: CueBy) => void): () => void {
  benchCues.add(heard);
  return () => benchCues.delete(heard);
}

/** The person drives a player on this page the way she does: every screen listening for cues hears it, none is told
 * over the network, and nothing is logged on the bench. */
export function cueBenchPlayer(bench: number, piece: number, cue: Cue): void {
  benchCues.forEach((h) => h(bench, piece, cue, 'person'));
}

/** Calls `readBack` whenever what is shown may be out of date: the feed (re)opened or fell behind. */
export function onResync(readBack: () => void): () => void {
  resyncs.add(readBack);
  return () => resyncs.delete(readBack);
}
