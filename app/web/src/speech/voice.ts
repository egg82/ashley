// Her answer played aloud on the page a person spoke to her from: the one owner of audio playback for a page (the web
// chat, the kiosk). Audio is unlocked inside the record button's tap (`primeVoice`), since phone browsers refuse what a
// page starts later; a window opens when a message said aloud is sent (`awaitVoice`) and plays her voiced turns that
// arrive in it (`offer`), in this tab only.
import { signal, type ReadonlySignal } from '@preact/signals';
import { chatVoiceUrl, getSpokenLimits } from '../api/speech';

/** A turn as the conversation read-back lists it: the fields playback decides on. */
export interface VoiceTurn {
  id: number;
  author: 'person' | 'ashley' | 'household';
  follows: boolean;
  voiced: boolean;
}

/** `playing`: this turn's voice is playing; `blocked`: the browser refused to start it, so a control plays it on a tap. */
export interface VoiceState {
  turn: number;
  phase: 'playing' | 'blocked';
}

interface Listening {
  seen: ReadonlySet<number>;
  timer: ReturnType<typeof setTimeout> | undefined;
}

/** One second of nothing, which an `<audio>` element plays inside a tap so that it may play others afterwards. */
const SILENCE = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=';

const current = signal<VoiceState | null>(null);
export const state: ReadonlySignal<VoiceState | null> = current;
const heard = signal(false);
/** Her voice is audible now: the browser said the element is playing, which is later than `state` says `playing` (the
 * answer is synthesised when it is fetched). Her mark speaks by this. */
export const sounding: ReadonlySignal<boolean> = heard;

let route: (turn: number) => string = chatVoiceUrl;
let audio: HTMLAudioElement | null = null;
let context: AudioContext | null = null;
let open: Listening | null = null;
let queue: number[] = [];
let playing: number | null = null;
const taken = new Set<number>();

/** Says which GET route her voice for a turn is read from; the room that owns playback calls it on entering. */
export function voiceRoute(urlOf: (turn: number) => string): void {
  route = urlOf;
}

function player(): HTMLAudioElement {
  audio ??= new Audio();
  return audio;
}

/** Unlocks audio for later playback. Called synchronously inside the record button's tap, before any await. */
export function primeVoice(): void {
  const element = player();
  element.src = SILENCE;
  void element.play()?.catch(() => undefined);
  if (typeof AudioContext !== 'function') return;
  context ??= new AudioContext();
  void context.resume().catch(() => undefined);
  const source = context.createBufferSource();
  source.buffer = context.createBuffer(1, 1, context.sampleRate);
  source.connect(context.destination);
  source.start();
}

function closeWindow(which: Listening | null): void {
  if (which === null) return;
  clearTimeout(which.timer);
  if (open === which) open = null;
}

/** Opens the window in which her voiced turns play: closes on her first turn that does not `follows`, after `voice_s`,
 * or on the next send. `seen` is the ids of the turns already shown. */
export function awaitVoice(seen: ReadonlySet<number>): void {
  closeWindow(open);
  queue = [];
  taken.clear();
  const mine: Listening = { seen, timer: undefined };
  open = mine;
  void getSpokenLimits()
    .then((limits) => {
      if (open === mine) mine.timer = setTimeout(() => closeWindow(mine), limits.voice_s * 1000);
    })
    .catch(() => undefined);
}

function finished(): void {
  playing = null;
  heard.value = false;
  const next = queue.shift();
  if (next === undefined) current.value = null;
  else begin(next);
}

function begin(turn: number): void {
  const element = player();
  playing = turn;
  current.value = { turn, phase: 'playing' };
  heard.value = false;
  element.onended = element.onerror = () => finished();
  element.onplaying = () => {
    if (playing === turn) heard.value = true;
  };
  element.src = route(turn);
  void element.play()?.catch((error: unknown) => {
    if (playing !== turn) return;
    if (error instanceof DOMException && error.name === 'NotAllowedError') current.value = { turn, phase: 'blocked' };
    else finished();
  });
}

/** Plays turn `turn` now, from a tap on its play control; the turns queued behind it follow. */
export function playTurn(turn: number): void {
  begin(turn);
}

/** After each conversation read: while the window is open, plays, in order and once each, every turn of hers that is
 * not in `seen`, is `voiced` and was read in this tab. */
export function offer(turns: readonly VoiceTurn[]): void {
  for (const t of turns) {
    const listening = open;
    if (listening === null) return;
    if (t.author !== 'ashley' || listening.seen.has(t.id) || taken.has(t.id)) continue;
    taken.add(t.id);
    if (t.voiced) {
      if (playing === null) begin(t.id);
      else queue.push(t.id);
    }
    if (!t.follows) closeWindow(listening);
  }
}

/** Whether this page's voice has her answer in hand: its window is open, or a turn plays or waits for a tap. */
export function owns(): boolean {
  return open !== null || current.value !== null;
}

/** Pauses and drops the current audio and closes the window: tapping record again, a typed send, the room left. */
export function stopVoice(): void {
  closeWindow(open);
  queue = [];
  playing = null;
  current.value = null;
  heard.value = false;
  if (audio === null) return;
  audio.onended = audio.onerror = audio.onplaying = null;
  audio.pause();
}
