// What the kiosk holds: whether this screen is paired, its conversation, the glance and the controls, and her state as
// the kiosk shows it. Every read goes through `refresh`: the live feed (`live.ts`) calls it when the conversation
// changes or may have been missed, and `startPolling` calls it on the timers of `polling.ts`.
import { computed, signal } from '@preact/signals';
import {
  ApiError,
  getKioskControls,
  kioskVoiceUrl,
  getKioskConversation,
  getKioskDevice,
  getKioskGlance,
  getKioskLayout,
  pairKiosk,
  runKioskControl,
  sendKiosk,
  transcribeKiosk,
} from '../api/client';
import type { KioskControl, KioskDevice, KioskGlance } from '../api/types';
import type { MarkState } from '../components/AshleyMark';
import type { Line, Missed } from '../rooms/her/chat';
import { missedFor } from '../rooms/her/overlay';
import { owedAt } from '../rooms/her/owed';
import { watchBuild, type Watch } from '../session/watch';
import { talk, type TalkPhase } from '../speech/talk';
import { awaitVoice, offer, owns, sounding, stopVoice, voiceRoute } from '../speech/voice';
import { validLayout, type Layout } from './layout';
import { listenScreen, liveMark, liveUp, startLive } from './live';
import { polled, POLL_MS, type Part } from './polling';

export type { Part };

export type Pairing = 'checking' | 'unpaired' | 'paired' | 'unreachable';
export type ControlState = 'running' | 'done' | 'failed' | 'busy';

export const pairing = signal<Pairing>('checking');
export const device = signal<KioskDevice | null>(null);
export const lines = signal<readonly Line[]>([]);
/** The last glance read; null until one is, or while it cannot be. */
export const glance = signal<KioskGlance | null>(null);
export const controls = signal<readonly KioskControl[]>([]);
/** The screen's layout as she arranged it, or null: not read yet, failed, malformed or never laid out, when the page shows
 * its fixed arrangement. */
export const layout = signal<Layout | null>(null);
export const controlStates = signal<Readonly<Record<string, ControlState>>>({});
export const sending = signal(false);
/** What this screen itself knows of her: someone is talking to her here, a message it sent is unanswered, its reply just
 * landed, she cannot be reached. */
const own = signal<MarkState>('idle');
/** Her mark: what this screen knows first, else what the live feed says she is doing. */
export const mark = computed<MarkState>(() =>
  sounding.value ? 'speaking' : own.value === 'idle' ? liveMark.value : own.value);

const SPEAKING_MS = 2500;
const CONTROL_SHOWN_MS = 2500;

let localKey = 0;

function line(author: Line['author'], text: string): Line {
  return { key: `l${localKey++}`, author, text, at: new Date().toISOString() };
}

/** A 401 anywhere means the screen is no longer paired (never paired, or its device revoked). */
function unpairedBy(error: unknown): boolean {
  if (error instanceof ApiError && error.status === 401) {
    pairing.value = 'unpaired';
    device.value = null;
    return true;
  }
  return false;
}

function missedOf(error: unknown): Missed {
  if (!(error instanceof ApiError)) return 'unreachable';
  if (error.status === 422) return 'refused';
  return error.status === 503 ? 'unreachable' : 'failed';
}

function sameTalk(a: readonly Line[], b: readonly Line[]): boolean {
  return a.length === b.length && a.every((l, i) => l.author === b[i]!.author && l.text === b[i]!.text && l.turn === b[i]!.turn && l.runs?.length === b[i]!.runs?.length && JSON.stringify(l.receipts) === JSON.stringify(b[i]!.receipts));
}

async function readLayout(): Promise<void> {
  try {
    layout.value = validLayout(await getKioskLayout());
  } catch (error) {
    layout.value = null;
    unpairedBy(error);
  }
}

/** Reads one part again. The live feed's entry point. */
export async function refresh(part: Part): Promise<void> {
  try {
    if (part === 'glance') {
      glance.value = await getKioskGlance();
      return;
    }
    if (part === 'layout') {
      await Promise.all([readLayout(), loadControls()]);
      return;
    }
    if (sending.value) return;
    const got = await getKioskConversation();
    const read = got.turns.map((t): Line => ({ key: `t${t.id}`, author: t.author, text: t.text, at: t.at, turn: t.id, follows: t.follows, runs: t.runs, receipts: t.receipts ?? undefined }));
    offer(got.turns.map((t) => ({ id: t.id, author: t.author, follows: t.follows, voiced: t.voiced })));
    if (!sameTalk(read, lines.value)) lines.value = read;
    if (own.value === 'unreachable') own.value = 'idle';
  } catch (error) {
    if (unpairedBy(error)) return;
    if (part === 'glance') glance.value = null;
    else if (missedOf(error) === 'unreachable') own.value = 'unreachable';
  }
}

/** Reads every part on its own timer (`polled` says when), until the returned stop is called. */
export function startPolling(): () => void {
  const timers = (Object.keys(POLL_MS) as Part[]).map((part) =>
    setInterval(() => {
      if (!document.hidden && polled(part, liveUp.value) && pairing.value === 'paired') void refresh(part);
    }, POLL_MS[part]),
  );
  return () => timers.forEach(clearInterval);
}

/** Opens the live feed for a paired screen: the conversation is read back on a stored turn, every part on a resync
 * (the feed opened or fell behind). The page also follows the server's build, and does not reload while she is
 * listening, thinking or speaking, or a message is going. Returns the stop. */
export function startFeed(): () => void {
  voiceRoute(kioskVoiceUrl);
  const watcher: Watch = watchBuild(() => sending.value || mark.value !== 'idle' || talking.phase.value !== 'idle');
  listenScreen((changed) => {
    if (changed === device.value?.id) void refresh('layout');
  });
  const stopLive = startLive(
    () => void refresh('conversation'),
    () => {
      void Promise.all([refresh('conversation'), refresh('glance'), refresh('layout')]);
      watcher.check();
    },
    (why) => {
      const owed = owedAt(lines.value);
      const missed = missedFor(why);
      if (owed >= 0) lines.value = lines.value.map((l, i) => (i === owed ? { ...l, missed } : l));
    },
  );
  return () => {
    stopLive();
    watcher.stop();
    stopVoice();
  };
}

async function loadPaired(): Promise<void> {
  pairing.value = 'paired';
  await Promise.all([refresh('conversation'), refresh('glance'), refresh('layout')]);
}

async function loadControls(): Promise<void> {
  try {
    controls.value = (await getKioskControls()).controls;
  } catch (error) {
    unpairedBy(error);
  }
}

/** Finds out whether this screen is paired, and reads everything when it is. */
export async function start(): Promise<void> {
  pairing.value = 'checking';
  try {
    device.value = await getKioskDevice();
  } catch (error) {
    if (!unpairedBy(error)) pairing.value = 'unreachable';
    return;
  }
  await loadPaired();
}

/** Pairs with `token`; what went wrong, or null when it worked. */
export async function pair(token: string): Promise<'refused' | 'elsewhere' | 'unreachable' | null> {
  try {
    device.value = await pairKiosk(token);
  } catch (error) {
    if (!(error instanceof ApiError)) return 'unreachable';
    if (error.status === 401) return 'refused';
    return error.status === 403 ? 'elsewhere' : 'unreachable';
  }
  await loadPaired();
  return null;
}

/** Sends `text` (trimmed, non-empty) as the kiosk, said aloud when `aloud`, and appends her answer when it lands. */
export async function send(text: string, aloud = false): Promise<void> {
  const mine = line('person', text);
  if (aloud) awaitVoice(new Set(lines.value.flatMap((l) => (l.turn === undefined ? [] : [l.turn]))));
  else stopVoice();
  lines.value = [...lines.value, mine];
  sending.value = true;
  own.value = 'thinking';
  try {
    const reply = await sendKiosk({ text, said_aloud: aloud });
    if (!reply.body) {
      // Pending: her turn is being worked on elsewhere; the feed shows her thinking and the read-back brings the answer.
      own.value = 'idle';
      return;
    }
    lines.value = [...lines.value, { ...line('ashley', reply.body), follows: reply.follows, receipts: reply.receipts ?? undefined }];
    if (owns()) own.value = 'idle';
    else {
      own.value = 'speaking';
      setTimeout(() => {
        if (own.value === 'speaking') own.value = 'idle';
      }, SPEAKING_MS);
    }
  } catch (error) {
    if (unpairedBy(error)) return;
    const missed = missedOf(error);
    lines.value = lines.value.map((l) => (l === mine ? { ...l, missed } : l));
    own.value = missed === 'unreachable' ? 'unreachable' : 'idle';
  } finally {
    sending.value = false;
  }
  if (aloud) await refresh('conversation');
}

function heard(phase: TalkPhase): void {
  if (phase === 'listening') own.value = 'listening';
  else if (phase === 'hearing') own.value = 'thinking';
  else if (own.value === 'listening' || (own.value === 'thinking' && !sending.value)) own.value = 'idle';
}

/** Tap to talk at the kiosk: what is said is sent as if typed. */
export const talking = talk(
  async (audio) => {
    try {
      return await transcribeKiosk(audio);
    } catch (error) {
      unpairedBy(error);
      throw error;
    }
  },
  (text, aloud) => void send(text, aloud),
  heard,
);

function setControl(name: string, state: ControlState | null): void {
  const next = { ...controlStates.value };
  if (state === null) delete next[name];
  else next[name] = state;
  controlStates.value = next;
}

/** Carries out control `name`, showing it running, then done or failed for a moment. */
export async function press(name: string): Promise<void> {
  setControl(name, 'running');
  let shown: ControlState;
  try {
    shown = (await runKioskControl(name)) ? 'done' : 'failed';
  } catch (error) {
    if (unpairedBy(error)) return;
    shown = error instanceof ApiError && error.status === 429 ? 'busy' : 'failed';
  }
  setControl(name, shown);
  setTimeout(() => {
    if (controlStates.value[name] === shown) setControl(name, null);
  }, CONTROL_SHOWN_MS);
}
