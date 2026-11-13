// The line of what she is announcing (`announce.ts`), at the top of the screen while her voice plays: her mark speaking
// beside it, a play control when the browser refused to start her voice, and a control that sends it away.
import { AshleyMark } from '../components/AshleyMark';
import { announcement, dismiss, playAnnouncement } from './announce';

export function Announcement() {
  const shown = announcement.value;
  if (!shown) return null;
  return (
    <div class="announce" role="status">
      <AshleyMark state={shown.phase === 'playing' ? 'speaking' : 'idle'} size={36} />
      <p class="announce-line">{shown.line}</p>
      {shown.phase === 'blocked' && (
        <button class="btn sm primary" type="button" onClick={playAnnouncement}>Play</button>
      )}
      <button class="btn sm ghost" type="button" aria-label="Dismiss" onClick={dismiss}>✕</button>
    </div>
  );
}
