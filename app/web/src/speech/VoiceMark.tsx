// Under her line while her voice for it plays: a speaker mark and Stop; or, when the browser refused to start it, a Play
// control, whose tap is the gesture the browser wanted. Nothing shows for a line whose voice is not this page's to play.
import { playTurn, state, stopVoice } from './voice';

export function VoiceMark({ turn }: { turn: number }) {
  const now = state.value;
  if (now === null || now.turn !== turn) return null;
  if (now.phase === 'blocked') {
    return (
      <div class="voice-mark blocked">
        <button class="voice-btn" type="button" aria-label="Play Ashley's answer" onClick={() => playTurn(turn)}>
          <span aria-hidden="true">{'▶'}</span> Play
        </button>
      </div>
    );
  }
  return (
    <div class="voice-mark" role="status">
      <svg class="voice-icon" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M2 6h3l4-3v10l-4-3H2z" fill="currentColor" />
        <path d="M11 5.5a3.5 3.5 0 0 1 0 5M12.8 3.7a6 6 0 0 1 0 8.6" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
      </svg>
      <span>Speaking</span>
      <button class="voice-btn" type="button" aria-label="Stop her voice" onClick={stopVoice}>Stop</button>
    </div>
  );
}
