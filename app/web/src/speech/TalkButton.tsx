// The talk button at the left of a composer, and the line above it that says what the microphone is doing. Hold to
// talk and let go to send, or tap to start and tap again to send; Space and Enter do the same from the keyboard.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { Talk, TalkNote } from './talk';

/** A press held this long is hold-to-talk; a shorter one is a tap that leaves the microphone open. */
const HOLD_MS = 350;

const NOTE: Record<Exclude<TalkNote, 'cut' | 'too-long'>, string> = {
  denied: 'Microphone blocked. Allow it for this site to talk.',
  'no-mic': 'No microphone found.',
  unsupported: "This browser can't record here.",
  'nothing-heard': "Didn't catch anything. Try again.",
  unavailable: "Can't listen right now. Try again shortly.",
  failed: "That didn't send. Try again.",
};

function clock(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function seconds(talk: Talk): number {
  return Math.round((talk.maxMs.value ?? 0) / 1000);
}

function useElapsed(talk: Talk): number {
  const [now, setNow] = useState(() => performance.now());
  const listening = talk.phase.value === 'listening';
  useEffect(() => {
    if (!listening) return;
    setNow(performance.now());
    const timer = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(timer);
  }, [listening]);
  return Math.max(0, now - talk.since.value);
}

/** The line above the composer: listening and for how long, or what went wrong. Empty otherwise. */
export function TalkLine({ talk, held }: { talk: Talk; held: boolean }) {
  const elapsed = useElapsed(talk);
  const phase = talk.phase.value;
  const note = talk.note.value;
  let text = '';
  if (phase === 'listening') text = `Listening · ${clock(elapsed)} · ${held ? 'let go' : 'tap ●'} to send`;
  else if (note === 'cut') text = `Stopped at ${seconds(talk)} s and sent.`;
  else if (note === 'too-long') text = `That ran over ${seconds(talk)} s. Try a shorter one.`;
  else if (note) text = NOTE[note];
  return (
    <p class={`talk-line${phase === 'listening' ? ' on' : ''}${note && phase !== 'listening' ? ' note' : ''}`} role="status">
      {text}
    </p>
  );
}

/** The button. `onHeld` says whether the open recording is held (let go to send) or was tapped open. */
export function TalkButton({ talk, disabled, onHeld }: { talk: Talk; disabled: boolean; onHeld: (held: boolean) => void }) {
  const pressed = useRef<number | null>(null);
  const phase = talk.phase.value;
  const live = phase === 'opening' || phase === 'listening';
  useEffect(() => talk.cancel, [talk]);

  const down = () => {
    if (phase === 'listening') return talk.stop();
    if (phase !== 'idle' || disabled) return;
    pressed.current = performance.now();
    onHeld(true);
    talk.start();
  };
  const up = () => {
    const at = pressed.current;
    pressed.current = null;
    if (at === null) return;
    if (performance.now() - at >= HOLD_MS && talk.phase.value === 'listening') talk.stop();
    else onHeld(false);
  };
  const key = (e: KeyboardEvent, act: () => void) => {
    if (e.key !== ' ' && e.key !== 'Enter') return;
    e.preventDefault();
    if (!e.repeat) act();
  };
  return (
    <button
      class={`talk-btn${live ? ' live' : ''}${phase === 'hearing' ? ' hearing' : ''}`}
      type="button"
      aria-label={live ? 'Stop and send' : 'Talk'}
      aria-pressed={live}
      disabled={disabled && !live}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        down();
      }}
      onPointerUp={up}
      onPointerCancel={up}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={(e) => key(e, down)}
      onKeyUp={(e) => key(e, up)}
    >
      <span aria-hidden="true">●</span>
    </button>
  );
}
