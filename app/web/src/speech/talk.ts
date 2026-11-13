// Tap to talk for one composer: press to open the microphone, stop to send what was heard for a transcript, and hand
// the words to the composer's own send, so a spoken message is a typed one. What went wrong is a note, one at a time,
// cleared by the next press.
import { computed, signal, type ReadonlySignal } from '@preact/signals';
import { ApiError } from '../api/client';
import { getSpokenLimits } from '../api/speech';
import type { SpokenLimits, Transcript } from '../api/types';
import { MicRefused, record, type Recording } from './record';
import { primeVoice, stopVoice } from './voice';

/** `opening`: waiting for the microphone (and the browser's permission prompt); `hearing`: the transcript is coming. */
export type TalkPhase = 'idle' | 'opening' | 'listening' | 'hearing';
/** `cut`: the recording reached the longest utterance and was sent as it stood; `too-long`: the server refused it as longer. */
export type TalkNote =
  | 'denied'
  | 'no-mic'
  | 'unsupported'
  | 'cut'
  | 'too-long'
  | 'nothing-heard'
  | 'unavailable'
  | 'failed';

export interface Talk {
  phase: ReadonlySignal<TalkPhase>;
  note: ReadonlySignal<TalkNote | null>;
  /** When listening began (`performance.now()`), for the elapsed time. */
  since: ReadonlySignal<number>;
  /** The longest utterance, once known. Listening also ends by itself when the person stops talking. */
  maxMs: ReadonlySignal<number | null>;
  start(): void;
  stop(): void;
  /** Closes the microphone and drops whatever is in flight; nothing is sent. */
  cancel(): void;
}

const limits = signal<SpokenLimits | null>(null);
const longest = computed(() => limits.value?.max_ms ?? null);

async function spokenLimits(): Promise<SpokenLimits> {
  limits.value ??= await getSpokenLimits();
  return limits.value;
}

function noteOf(error: unknown): TalkNote {
  if (error instanceof MicRefused) return error.why;
  if (!(error instanceof ApiError)) return 'unavailable';
  if (error.status === 413) return 'too-long';
  return error.status === 503 ? 'unavailable' : 'failed';
}

export function talk(transcribe: (audio: Blob) => Promise<Transcript>, heard: (text: string, aloud: boolean) => void,
                     phaseChanged: (phase: TalkPhase) => void): Talk {
  const phase = signal<TalkPhase>('idle');
  const note = signal<TalkNote | null>(null);
  const since = signal(0);
  let recording: Recording | null = null;
  let turn = 0;

  const enter = (next: TalkPhase) => {
    phase.value = next;
    phaseChanged(next);
  };
  const fail = (mine: number, error: unknown) => {
    if (mine !== turn) return;
    recording?.cancel();
    recording = null;
    note.value = noteOf(error);
    enter('idle');
  };

  async function open(mine: number): Promise<void> {
    try {
      const { max_ms, speech_ms, silence_ms, quiet_rms } = await spokenLimits();
      const opened = await record(max_ms, () => {
        note.value = 'cut';
        stop();
      }, { speechMs: speech_ms, silenceMs: silence_ms, threshold: quiet_rms }, stop);
      if (mine !== turn) return opened.cancel();
      recording = opened;
      since.value = performance.now();
      enter('listening');
    } catch (error) {
      fail(mine, error);
    }
  }

  async function send(mine: number, opened: Recording): Promise<void> {
    try {
      const got = await transcribe(await opened.stop());
      if (mine !== turn) return;
      enter('idle');
      if (got.text.trim()) heard(got.text.trim(), true);
      else note.value = 'nothing-heard';
    } catch (error) {
      fail(mine, error);
    }
  }

  function start(): void {
    if (phase.value !== 'idle') return;
    stopVoice();
    primeVoice();
    note.value = null;
    enter('opening');
    void open(++turn);
  }

  function stop(): void {
    if (phase.value === 'opening') return cancel();
    if (phase.value !== 'listening' || !recording) return;
    const opened = recording;
    recording = null;
    enter('hearing');
    void send(turn, opened);
  }

  function cancel(): void {
    turn++;
    recording?.cancel();
    recording = null;
    if (phase.value !== 'idle') enter('idle');
  }

  return { phase, note, since, maxMs: longest, start, stop, cancel };
}
