// Her state as this client knows it, and its one owner: rooms and the live feed report what happened through the
// transitions below and never write a signal here. She is thinking while a message this client sent is unanswered,
// while a line the person asked her to remember is being decided, or while any turn the live feed reported (on any
// channel this person may see) is thinking; listening while the person talks to her here (thinking while that is
// transcribed), or while a live turn is (a satellite heard its wake word) and nothing else is going on; speaking for a
// moment as a reply lands here, or while a live turn is speaking; unreachable when `/api/health`, the session check or
// the shown room's own call failed; idle otherwise.
import { computed, signal } from '@preact/signals';
import type { MarkState } from '../../components/AshleyMark';
import { status } from '../../session/session';
import { revealing } from '../../signin/reveal';
import { markState } from './ladder';

const SPEAKING_MS = 1800;

const roomUnreachable = signal(false);
/** Messages sent from this client that have no reply yet. */
const asked = signal(0);
/** Lines the person asked her to remember whose decision has not come back. */
const remembering = signal(0);
const speaking = signal(false);
/** Her voice is playing on this page, as the audio element says. */
const voicePlaying = signal(false);
/** The shown room's conversation has a turn she is still working on, as the server read says; Live may not have said so. */
const working = signal(false);
/** The person talking to her from this page: the microphone is open, or what it heard is being transcribed. */
const hearing = signal<'listening' | 'transcribing' | null>(null);
let speakingTimer: ReturnType<typeof setTimeout> | undefined;
/** Turns the live feed reported that are not over, by token: what she is doing in each, and when to stop believing it. */
type Doing = 'listening' | 'thinking' | 'speaking';
const liveTurns = signal<ReadonlyMap<string, { state: Doing; timer: ReturnType<typeof setTimeout> }>>(new Map());

function live(state: Doing): boolean {
  for (const turn of liveTurns.value.values()) if (turn.state === state) return true;
  return false;
}

export const herState = computed<MarkState>(() =>
  markState({
    unreachable: status.value === 'unreachable' || roomUnreachable.value,
    checking: status.value === 'checking' || revealing.value,
    hearing: hearing.value,
    speaking: speaking.value || voicePlaying.value,
    liveSpeaking: live('speaking'),
    asked: asked.value,
    remembering: remembering.value,
    working: working.value,
    liveThinking: live('thinking'),
    liveListening: live('listening'),
  }));

/** The word under her mark: her state, or what is wrong when she cannot be reached. */
export const herWord = computed(() => (herState.value === 'unreachable' ? "can't reach her" : herState.value));

/** Whether the shown room's last call reached her (a 503, or no answer at all, did not). */
export function roomReached(reached: boolean): void {
  roomUnreachable.value = !reached;
}

function speak(): void {
  clearTimeout(speakingTimer);
  speaking.value = true;
  speakingTimer = setTimeout(() => (speaking.value = false), SPEAKING_MS);
}

/** A message from this client is on its way to her. */
export function herAsked(): void {
  asked.value += 1;
}

/** Her reply to one message landed. An answer she said would follow keeps her thinking through the live feed. A reply
 * whose voice this page plays (`voiced`) is not a moment of speaking: `herVoicePlaying` says when she is. */
export function herReplied(voiced = false): void {
  asked.value = Math.max(0, asked.value - 1);
  if (!voiced) speak();
}

/** A reply said outside the response to a message landed (read back after the live feed said so): she speaks, unless
 * this page plays it (`voiced`). */
export function herSaidLater(voiced = false): void {
  if (!voiced) speak();
}

/** Her voice started or stopped playing on this page. */
export function herVoicePlaying(on: boolean): void {
  voicePlaying.value = on;
}

/** A message from this client got no reply (refused, unreachable, or failed). */
export function herNoReply(): void {
  asked.value = Math.max(0, asked.value - 1);
}

/** The shown conversation, as last read, has a turn she is still working on (or no longer does). */
export function herWorking(on: boolean): void {
  working.value = on;
}

/** The person is talking to her from this page (`listening`), what they said is being transcribed, or neither. */
export function herHears(phase: 'listening' | 'transcribing' | null): void {
  hearing.value = phase;
}

/** The person asked her to remember a line: she thinks until `herRemembered`. */
export function herRemembering(): void {
  remembering.value += 1;
}

/** Her decision on a line to remember came back, whatever it was. */
export function herRemembered(): void {
  remembering.value = Math.max(0, remembering.value - 1);
}

/** The room that reported these left: nothing it was waiting for is waited for any more. Live turns go on. */
export function herRoomLeft(): void {
  roomUnreachable.value = false;
  asked.value = 0;
  remembering.value = 0;
  hearing.value = null;
  working.value = false;
  clearTimeout(speakingTimer);
  speaking.value = false;
  voicePlaying.value = false;
}

/**
 * The live feed says she is `state` in `turn`; a state other than idle is believed for `atMostMs` at most, since the
 * turn's end can be lost with the server that ran it.
 */
export function herLive(turn: string, state: Doing | 'idle', atMostMs: number): void {
  const next = new Map(liveTurns.value);
  clearTimeout(next.get(turn)?.timer);
  next.delete(turn);
  if (state !== 'idle') next.set(turn, { state, timer: setTimeout(() => herLive(turn, 'idle', 0), atMostMs) });
  liveTurns.value = next;
}

/** The live feed dropped or may have missed something: no turn it reported is believed any more. */
export function herLiveLost(): void {
  liveTurns.value.forEach((t) => clearTimeout(t.timer));
  liveTurns.value = new Map();
}
