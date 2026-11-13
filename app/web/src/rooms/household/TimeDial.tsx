// The household's time zone as a 24-hour dial, midnight at the top, with a hand for the local time now.
import { hour, locale } from '../../household/format';
import { momentIn } from './moment';
import { draft } from './state';
import { useNow } from './useNow';

const CENTER = 100;
const RADIUS = 86;

const at = (degrees: number, r: number) => {
  const a = (degrees * Math.PI) / 180;
  return { x: CENTER + r * Math.sin(a), y: CENTER - r * Math.cos(a) };
};

/** The wedge of the day that has passed, from midnight to `degrees`. */
function wedge(degrees: number): string {
  const end = at(degrees, RADIUS);
  return `M${CENTER} ${CENTER} L${CENTER} ${CENTER - RADIUS} A${RADIUS} ${RADIUS} 0 ${degrees > 180 ? 1 : 0} 1 ${end.x} ${end.y} Z`;
}

function Ticks() {
  return (
    <>
      {Array.from({ length: 24 }, (_, i) => {
        const major = i % 6 === 0;
        const a = at(i * 15, RADIUS);
        const b = at(i * 15, RADIUS - (major ? 11 : 5));
        return <line key={i} class={major ? 'tick major' : 'tick'} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
      })}
      {[0, 6, 12, 18].map((h) => {
        const p = at(h * 15, RADIUS - 24);
        return <text key={h} class="dial-n" x={p.x} y={p.y} text-anchor="middle" dominant-baseline="central">{h}</text>;
      })}
    </>
  );
}

export function TimeDial() {
  const d = draft.value;
  const now = useNow(30_000);
  if (!d) return null;
  const moment = momentIn(now, d.timezone, { locale: d.locale, clock: d.clock });
  const degrees = moment ? (moment.hours / 24) * 360 : 0;
  return (
    <figure class="hh-dial">
      <svg viewBox="0 0 200 200" role="img" aria-label={moment ? `${moment.text} in ${d.timezone}` : 'No time to show'}>
        <circle class="dial-face" cx={CENTER} cy={CENTER} r={RADIUS} />
        {moment && <path class="dial-past" d={wedge(degrees)} />}
        <Ticks />
        {moment && (
          <g class="dial-hand" style={{ transform: `rotate(${degrees}deg)` }}>
            <line x1={CENTER} y1={CENTER} x2={CENTER} y2={CENTER - RADIUS + 8} />
            <circle cx={CENTER} cy={CENTER - RADIUS + 8} r="5" />
          </g>
        )}
        <circle class="dial-pivot" cx={CENTER} cy={CENTER} r="3" />
      </svg>
      <figcaption>
        {moment ? (
          <>
            <b class="hh-clock">{now.toLocaleTimeString(locale({ locale: d.locale, clock: d.clock }),
              { timeZone: d.timezone, hour: hour({ locale: d.locale, clock: d.clock }), minute: '2-digit' })}</b>
            <span class="meta">{d.timezone} · {moment.offset}</span>
          </>
        ) : <span class="unk">not a time zone this browser knows</span>}
      </figcaption>
    </figure>
  );
}
