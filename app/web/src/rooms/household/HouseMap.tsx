// Where the house stands on a plain globe, or the reason it is not placed. There is no default place.
import { draft } from './state';
import { whereOf } from './pin';

const W = 360;
const H = 180;

export function HouseMap() {
  const d = draft.value;
  if (!d) return null;
  const where = whereOf(d.latitude, d.longitude);
  return (
    <div class="hh-map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={'pin' in where ? `The house at ${d.latitude}, ${d.longitude}` : 'The house is not on the map'}>
        {Array.from({ length: 11 }, (_, i) => <line key={`x${i}`} class={i === 6 ? 'grid eq' : 'grid'} x1={(i + 1) * 30} y1="0" x2={(i + 1) * 30} y2={H} />)}
        {Array.from({ length: 5 }, (_, i) => <line key={`y${i}`} class={i === 2 ? 'grid eq' : 'grid'} x1="0" y1={(i + 1) * 30} x2={W} y2={(i + 1) * 30} />)}
        {'pin' in where && (
          <g class="pin" transform={`translate(${where.pin.x * W} ${where.pin.y * H})`}>
            <circle r="10" class="pin-ring" /><circle r="3.5" />
          </g>
        )}
      </svg>
      {'unknown' in where
        ? <span class="unk hh-map-unk">Not on the map: {where.unknown.toLowerCase()}</span>
        : <span class="meta hh-map-at">{d.latitude}, {d.longitude}</span>}
    </div>
  );
}
