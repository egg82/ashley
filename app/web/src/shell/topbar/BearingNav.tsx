// The rooms by compass bearing from her. A bottom bar on phones. A room something is being carried to lights as the
// drop target (`shell/carry.ts`). The room she went to while the page waited (`her/moves.ts`) holds her away dock.
import { carryOver, carryTo } from '../carry';
import { waiting } from '../her/moves';
import { NAV, type RoomId } from '../rooms';

export function BearingNav({ current }: { current: RoomId }) {
  const away = waiting.value?.room;
  return (
    <nav class="bearing" aria-label="Rooms">
      {NAV.map((r) => (
        <a key={r.id} href={r.path} data-room={r.id} aria-current={r.id === current ? 'page' : undefined}
          class={r.id === carryTo.value ? (carryOver.value ? 'target catch' : 'target') : r.id === away ? 'her-there' : undefined}>
          <span class="deg">{r.bearing}</span>
          <span class="lbl">{r.label}</span>
          {r.id === away && <span class="away-dock" data-dock-away />}
        </a>
      ))}
    </nav>
  );
}
