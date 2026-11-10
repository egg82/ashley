// What her room holds: the conversation as the server stored it, read back whenever the live feed says the person's
// web thread got a turn (so every tab open on it shows every reply), with what this page alone knows laid over its
// end until a read-back has it: a message on its way, her reply as it landed, her "let me check" until it is stored,
// and a message that got no reply. A stored "let me check" (`follows`) stays, with the answer under it once it lands. Her state is reported to `shell/her/state.ts` from here and nowhere else in
// the room.
import { computed, effect, signal } from '@preact/signals';
import { ApiError, chatVoiceUrl, getChat, sendChat, transcribeChat } from '../../api/client';
import type { ChatAttachment } from '../../api/types';
import { liveUp, onResync, onThreadTurn, onTurnFailed, type TurnFailedWhy } from '../../session/live';
import { load as reloadSession } from '../../session/session';
import {
  herAsked,
  herHears,
  herNoReply,
  herReplied,
  herVoicePlaying,
  herRoomLeft,
  herWorking,
  herSaidLater,
  herState,
  roomReached,
} from '../../shell/her/state';
import { talk } from '../../speech/talk';
import { awaitVoice, offer, owns, sounding, stopVoice, voiceRoute } from '../../speech/voice';
import { stillOn } from './owed';
import { awaiting, failedLine, overlaid, storedLine, type Line, type Missed } from './overlay';
export { awaiting, failedLine, overlaid, type Line, type Missed, type Overlay } from './overlay';
import { keptReset } from './remember';
import { endsOnHeldLine, STALL_MS, stalledLine } from './stalled';

export type Load = 'loading' | 'ready' | 'unreachable' | 'failed';
export const loadState = signal<Load>('loading');
export const startedAt = signal<string | null>(null);
/** The open conversation's id, as last read back; null when none is open. */
export const conversationId = signal<number | null>(null);
/** Whether a message of the person's is waiting for her reply; the composer sends one at a time. */
export const sending = signal(false);

/** While the live feed is down, the conversation is read back this often. */
const FALLBACK_MS = 10000;

/** The conversation as last read back. */
const stored = signal<readonly Line[]>([]);
/** The person's message this page sent, until a read-back has it. */
const outgoing = signal<Line | null>(null);
/** Her reply as it landed here, until a read-back has it; a held one until the stored conversation ends with hers. */
const reply = signal<{ line: Line; held: boolean } | null>(null);
/** The last message of this page's that got no reply, and why. */
const unanswered = signal<Line | null>(null);

let localKey = 0;
let thread: string | null = null;
let reads = 0;
let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
/** Counts each entering of the room; work begun in an earlier visit reports nothing once it lands. */
let visit = 0;
let shown = false;
let unsubscribe: (() => void)[] = [];

/** A line only this page knows yet. */
export function line(author: Line['author'], text: string): Line {
  return { key: `l${localKey++}`, author, text, at: new Date().toISOString() };
}

export const lines = computed<readonly Line[]>(() =>
  overlaid(stored.value, { failed: unanswered.value, mine: outgoing.value, hers: reply.value }));

/** Whether her thinking belongs in this thread: a message here is unanswered, not only a turn on another channel. */
export const threadThinking = computed(() => awaiting(lines.value, sending.value, herState.value === 'thinking'));

/** Why a message got no reply, from what its send threw; a 401 reloads the session. */
export function missedOf(error: unknown): Missed {
  if (!(error instanceof ApiError)) return 'unreachable';
  if (error.status === 401) void reloadSession();
  if (error.status === 422) return 'refused';
  return error.status === 503 ? 'unreachable' : 'failed';
}

/** Reads the open conversation back. A read that a later one overtook changes nothing. */
async function readBack(): Promise<void> {
  const mine = ++reads;
  const got = await getChat();
  if (mine !== reads) return;
  const hers = (all: readonly { author: string }[]) => all.filter((t) => t.author === 'ashley').length;
  const more = hers(got.turns) > hers(stored.value);
  thread = got.thread;
  stored.value = got.turns.map(storedLine);
  offer(got.turns.map((t) => ({ id: t.id, author: t.author, follows: t.follows, voiced: t.voiced })));
  startedAt.value = got.started_at;
  herWorking(stillOn(stored.value));
  conversationId.value = got.conversation_id;
  if (!sending.value) outgoing.value = null;
  if (reply.value && (!reply.value.held || stored.value.at(-1)?.author === 'ashley')) reply.value = null;
  if (more && loadState.value === 'ready' && !sending.value) herSaidLater(owns());
}

/** Reads the open conversation back, showing that it is loading; the room's first read and "Try again". */
export async function loadChat(): Promise<void> {
  loadState.value = 'loading';
  roomReached(true);
  try {
    await readBack();
    loadState.value = 'ready';
  } catch (error) {
    const missed = missedOf(error);
    loadState.value = missed === 'unreachable' ? 'unreachable' : 'failed';
    roomReached(missed !== 'unreachable');
  }
}

/** Reads back without showing a load; a failure keeps what is shown and reports whether she was reached. Work the server
 * last said it had in flight is not believed past a read it could not answer. */
export async function refresh(): Promise<void> {
  if (loadState.value !== 'ready') return loadChat();
  try {
    await readBack();
    roomReached(true);
  } catch (error) {
    const missed = missedOf(error);
    if (missed === 'unreachable') {
      stored.value = stored.value.map((l) => (l.working ? { ...l, working: false } : l));
      herWorking(false);
    }
    roomReached(missed !== 'unreachable');
  }
}

/** Marks the line owed an answer unfinished once the conversation has sat on her held line for `STALL_MS` with her
 * neither thinking nor working; stops when either comes back or an answer is stored. */
function watchStall(): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const stop = effect(() => {
    clearTimeout(timer);
    if (!endsOnHeldLine(stored.value) || threadThinking.value) return;
    timer = setTimeout(() => {
      unanswered.value = stalledLine(stored.value);
    }, STALL_MS);
  });
  return () => {
    stop();
    clearTimeout(timer);
  };
}

/** Sends `text` (already trimmed, non-empty) and the paste that came with it, if any, shows her reply as it lands, then
 * reads the conversation back. `aloud` says the words came from the record button. Resolves to why the message was not taken, which is never so here. */
export async function send(text: string, pasted: string | null = null, aloud = false): Promise<string | null> {
  const attachment: ChatAttachment | undefined = pasted === null ? undefined : { title: null, text: pasted };
  const mine = { ...line('person', text), attachment };
  const here = visit;
  if (aloud) awaitVoice(new Set(stored.value.flatMap((l) => (l.turn === undefined ? [] : [l.turn]))));
  else stopVoice();
  unanswered.value = null;
  outgoing.value = mine;
  sending.value = true;
  herAsked();
  try {
    const got = await sendChat(attachment ? { text, attachment, said_aloud: aloud } : { text, said_aloud: aloud });
    if (here !== visit) return null;
    reply.value = { line: { ...line('ashley', got.body), follows: got.follows, receipts: got.receipts ?? undefined }, held: got.follows };
    startedAt.value ??= mine.at;
    roomReached(true);
    if (got.body) herReplied(owns());
    else herNoReply();
  } catch (error) {
    if (here !== visit) return null;
    const missed = missedOf(error);
    unanswered.value = { ...mine, missed };
    outgoing.value = null;
    roomReached(missed !== 'unreachable');
    herNoReply();
  } finally {
    if (here === visit) sending.value = false;
  }
  if (here === visit) await refresh();
  return null;
}

/** Tap to talk in this room: what the person says is sent as if typed. */
export const talking = talk(
  async (audio) => {
    try {
      return await transcribeChat(audio);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) void reloadSession();
      throw error;
    }
  },
  (text, aloud) => void send(text, null, aloud),
  (phase) => herHears(phase === 'listening' ? 'listening' : phase === 'hearing' ? 'transcribing' : null),
);

function fallback(here: number): void {
  if (!liveUp.value && !document.hidden) void refresh();
  if (shown && here === visit) fallbackTimer = setTimeout(() => fallback(here), FALLBACK_MS);
}

/** The room is shown: read the conversation, then read it back whenever its thread gets a turn, until it is left. */
export function enterRoom(): void {
  const here = ++visit;
  shown = true;
  voiceRoute(chatVoiceUrl);
  sending.value = false;
  outgoing.value = reply.value = unanswered.value = null;
  keptReset();
  unsubscribe = [
    onThreadTurn((t) => t === thread && void refresh()),
    onTurnFailed((t, why) => {
      if (t !== thread) return;
      stored.value = stored.value.map((l) => (l.working ? { ...l, working: false } : l));
      herWorking(false);
      unanswered.value = failedLine(stored.value, why);
      reply.value = null;
    }),
    onResync(() => void refresh()),
    watchStall(),
    effect(() => herVoicePlaying(sounding.value)),
  ];
  void loadChat().then(() => {
    if (shown && here === visit) fallbackTimer = setTimeout(() => fallback(here), FALLBACK_MS);
  });
}

/** The room is left: stop reading back, and her state stops answering for it. */
export function leaveRoom(): void {
  shown = false;
  visit++;
  clearTimeout(fallbackTimer);
  unsubscribe.forEach((u) => u());
  unsubscribe = [];
  keptReset();
  talking.cancel();
  stopVoice();
  herRoomLeft();
}
