// A bench's talk: the conversation on the bench's own thread, read back whenever the live feed says that thread got a
// turn, with what only this page knows laid over its end (her room's `overlaid`). The lines and composer are her
// room's; only the routes differ.
import { computed, signal } from '@preact/signals';
import { getBenchConversation, getBenchPage, sendOnBench, transcribeChat } from '../../../api/client';
import { onResync, onThreadTurn, onTurnFailed } from '../../../session/live';
import { herAsked, herHears, herNoReply, herReplied, herRoomLeft, herSaidLater, herState, herWorking } from '../../../shell/her/state';
import { talk } from '../../../speech/talk';
import { firstLine } from '../../her/attached';
import { apply } from './bench';
import { whyNot } from '../pieces/why';
import { awaiting, failedLine, line, missedOf, overlaid, type Line, type Overlay } from '../../her/chat';
import { stillOn } from '../../her/owed';
import { earlierStream } from '../../her/past';
import { rules, unreachable } from './benches';

/** The longest title a paste is given, when the bench's own limit is not known yet. */
const PASTE_TITLE = 60;

export type TalkLoad = 'loading' | 'ready' | 'unreachable' | 'failed';

export const talkState = signal<TalkLoad>('loading');
export const talkConversation = signal<number | null>(null);
export const talkSending = signal(false);
export const talkStartedAt = signal<string | null>(null);

/** The bench's earlier conversations, closed ones included, above the open one. */
export const benchEarlier = earlierStream((limit, before) => {
  if (openId === null) return Promise.reject(new Error('no bench is open'));
  return getBenchPage(openId, limit, before);
});

const stored = signal<readonly Line[]>([]);
const overlay = signal<Overlay>({ failed: null, mine: null, hers: null });

let openId: number | null = null;
let thread: string | null = null;
let reads = 0;
let unsubscribe: (() => void)[] = [];

export const talkLines = computed(() => overlaid(stored.value, overlay.value));

export const talkThinking = computed(() => awaiting(talkLines.value, talkSending.value, herState.value === 'thinking'));

async function readBack(id: number): Promise<void> {
  const mine = ++reads;
  const got = await getBenchConversation(id);
  if (mine !== reads || id !== openId) return;
  const hers = (all: readonly { author: string }[]) => all.filter((t) => t.author === 'ashley').length;
  const more = hers(got.turns) > hers(stored.value);
  stored.value = got.turns.map((t) => ({ key: `t${t.id}`, author: t.author, text: t.text, at: t.at, turn: t.id, follows: t.follows, runs: t.runs, looks: t.looks, working: t.working }));
  talkConversation.value = got.conversation_id;
  talkStartedAt.value = got.started_at;
  herWorking(stillOn(stored.value));
  const o = overlay.value;
  const hersDone = o.hers && (!o.hers.held || stored.value.at(-1)?.author === 'ashley');
  overlay.value = { ...o, mine: talkSending.value ? o.mine : null, hers: hersDone ? null : o.hers };
  if (more && talkState.value === 'ready' && !talkSending.value) herSaidLater();
}

async function load(id: number, quiet: boolean): Promise<void> {
  if (!quiet) talkState.value = 'loading';
  try {
    await readBack(id);
    talkState.value = 'ready';
  } catch (error) {
    if (id === openId && (!quiet || talkState.value !== 'ready')) talkState.value = unreachable(error) ? 'unreachable' : 'failed';
  }
}

export function retryTalk(): Promise<void> {
  return openId === null ? Promise.resolve() : load(openId, false);
}

/** The piece a paste becomes on the bench: a large document, titled by its first line. */
async function putUp(pasted: string, titleMax: number): Promise<{ piece: number } | { why: string }> {
  const title = firstLine(pasted, Math.min(titleMax, PASTE_TITLE)) || 'Pasted text';
  const got = await apply({ type: 'add', kind: 'document', title, body: pasted, size: 'large' });
  if (!got.ok) return { why: whyNot(got.why) };
  return got.piece === null ? { why: whyNot('failed') } : { piece: got.piece };
}

/** Sends `text` (trimmed, non-empty) on the open bench's talk, shows her reply as it lands, then reads back. A paste
 * that came with it is first put on the bench as a document by the person, so it is undoable and shows at once, and the
 * message names it. Resolves to why nothing was sent, when the paste could not be put up; null otherwise. */
export async function sendTalk(text: string, pasted: string | null = null): Promise<string | null> {
  const id = openId;
  if (id === null) return null;
  let piece: number | undefined;
  if (pasted !== null) {
    const put = await putUp(pasted, rules.value?.title_max_chars ?? PASTE_TITLE);
    if ('why' in put) return put.why;
    piece = put.piece;
  }
  const mine = line('person', text);
  overlay.value = { ...overlay.value, failed: null, mine };
  talkSending.value = true;
  herAsked();
  try {
    const got = await sendOnBench(id, piece === undefined ? { text } : { text, piece_id: piece });
    if (id !== openId) return null;
    overlay.value = { ...overlay.value, hers: { line: { ...line('ashley', got.body), follows: got.follows }, held: got.follows } };
    if (got.body) herReplied();
    else herNoReply();
  } catch (error) {
    if (id !== openId) return null;
    overlay.value = { ...overlay.value, failed: { ...mine, missed: missedOf(error) }, mine: null };
    herNoReply();
  } finally {
    if (id === openId) talkSending.value = false;
  }
  if (id === openId) await load(id, true);
  return null;
}

export const benchTalking = talk(
  (audio) => transcribeChat(audio),
  (text) => void sendTalk(text),
  (phase) => herHears(phase === 'listening' ? 'listening' : phase === 'hearing' ? 'transcribing' : null),
);

/** Bench `id`, whose talk is on `benchThread`, is shown: read its talk, and read it back on each turn there. */
export function enterTalk(id: number, benchThread: string): void {
  if (openId === id) return;
  leaveTalk();
  openId = id;
  thread = benchThread;
  stored.value = [];
  overlay.value = { failed: null, mine: null, hers: null };
  talkConversation.value = null;
  talkStartedAt.value = null;
  talkSending.value = false;
  benchEarlier.earlierReset();
  unsubscribe = [
    onThreadTurn((t) => t === thread && void load(id, true)),
    onTurnFailed((t, why) => {
      if (t !== thread) return;
      stored.value = stored.value.map((l) => (l.working ? { ...l, working: false } : l));
      herWorking(false);
      overlay.value = { ...overlay.value, failed: failedLine(stored.value, why), hers: null };
    }),
    onResync(() => void load(id, true)),
  ];
  void load(id, false);
}

export function leaveTalk(): void {
  if (openId === null) return;
  openId = null;
  thread = null;
  reads++;
  unsubscribe.forEach((u) => u());
  unsubscribe = [];
  benchTalking.cancel();
  herRoomLeft();
}
