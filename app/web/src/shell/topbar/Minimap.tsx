// The field at a glance: a dot per room, and a frame for where the camera points, which flies with it. A room
// something is being carried to lights its dot (`shell/carry.ts`).
import { carryOver, carryTo } from '../carry';
import { camera } from '../flight';
import { FIELD, NAV, room } from '../rooms';

const SCALE = 100 / FIELD;

export function Minimap() {
  const at = camera.value;
  const [cx, cy] = room(at).at.map((v) => v * SCALE) as [number, number];
  return (
    <div class="minimap">
      <svg viewBox="0 0 100 100" role="img" aria-label="Map of rooms">
        <circle cx="50" cy="50" r="43" fill="none" stroke="#2a4566" />
        <circle cx="50" cy="50" r="22" fill="none" stroke="#1b2d44" />
        {NAV.map((r) => {
          const [x, y] = r.at.map((v) => v * SCALE) as [number, number];
          return (
            <g key={r.id}>
              <circle class={r.id === carryTo.value ? `dot target${carryOver.value ? ' catch' : ''}` : 'dot'} cx={x} cy={y}
                r="4.5" fill={r.id === at ? '#4da3ff' : '#5d7290'} />
              <text class="labels" x={x} y={y + (y > 50 ? 12 : -8)} fill="#5d7290" font-size="7"
                font-family="JetBrains Mono" text-anchor="middle">{r.bearing}</text>
            </g>
          );
        })}
        <g class="cam" style={{ transform: `translate(${cx}px, ${cy}px)` }}>
          <rect x="-9" y="-7" width="18" height="14" fill="rgba(77,163,255,.14)" stroke="#5fe1ff" stroke-width="1" />
        </g>
      </svg>
    </div>
  );
}
