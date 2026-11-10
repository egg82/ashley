// The crosshair around her on the sign-in face: it turns while she loads and locks when she is ready.
import { locked } from './reveal';

export function Reticle() {
  return (
    <div class={`reticle${locked.value ? ' locked' : ''}`}>
      <svg class="ret-ring" viewBox="0 0 200 200" aria-hidden="true">
        <circle cx="100" cy="100" r="92" fill="none" stroke="rgba(77,163,255,.35)" stroke-dasharray="2 6" />
        <circle cx="100" cy="100" r="78" fill="none" stroke="rgba(95,225,255,.5)" stroke-dasharray="60 62" />
        <path d="M100 0v22M100 178v22M0 100h22M178 100h22" stroke="#5fe1ff" stroke-width="2" />
      </svg>
      <span class="si-dock" data-dock />
    </div>
  );
}
