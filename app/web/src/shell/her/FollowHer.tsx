// The offer to follow her while the page stayed (`moves.ts`): below the bearing her mark waits at in the top bar; on a
// phone, whose bearings are a bottom bar under the composer, at the top, clear of what the person is typing.
import { useEffect, useState } from 'preact/hooks';
import { bearingOf } from '../carry';
import { NAV } from '../rooms';
import { followHer, stayHere, waiting, type Waiting } from './moves';

function wentTo(to: Waiting): string {
  if (to.room === 'her') return 'back to chat';
  if (to.path !== NAV.find((r) => r.id === to.room)!.path) return 'to a bench';
  return `to ${NAV.find((r) => r.id === to.room)!.label}`;
}

function placeBy(to: Waiting): Record<string, string> {
  const at = bearingOf(to.room)?.getBoundingClientRect();
  if (!at || at.top > window.innerHeight / 2) return { top: '60px', left: '50%', transform: 'translateX(-50%)' };
  return { right: `${Math.max(8, Math.min(window.innerWidth - at.right, window.innerWidth - 300))}px`, top: `${at.bottom + 10}px` };
}

export function FollowHer() {
  const to = waiting.value;
  const [, resized] = useState(0);
  useEffect(() => {
    const again = () => resized((n) => n + 1);
    addEventListener('resize', again);
    return () => removeEventListener('resize', again);
  }, []);
  if (!to) return null;
  return (
    <div class="follow-her" role="status" style={placeBy(to)}>
      <span>Ashley went {wentTo(to)}</span>
      <button class="btn sm primary" type="button" onClick={followHer}>Follow</button>
      <button class="btn sm ghost" type="button" onClick={stayHere}>Stay</button>
    </div>
  );
}
