// The one field every room sits on: range rings, a bearing scale, a sector arc and drifting points per room, and a
// slow sweep. Drawn once at field scale; the camera moves the whole of it.
import { CENTRE as C, FIELD, polar } from '../rooms';

const RINGS = [260, 560, 900, 1300, 1750];
const SECTORS: readonly [number, string][] = [[315, 'MEMORY'], [180, 'WORKSHOP'], [70, 'DEVICES'], [250, 'CONNECTIONS']];

function Rings() {
  return (
    <>
      {RINGS.map((r, i) => (
        <circle key={r} cx={C} cy={C} r={r} fill="none" stroke={`rgba(77,163,255,${0.22 - i * 0.03})`}
          stroke-width={i ? 1.5 : 2.5} stroke-dasharray={i % 2 ? '4 10' : undefined} />
      ))}
    </>
  );
}

function Scale() {
  const ticks = [];
  for (let d = 0; d < 360; d += 5) {
    const [x1, y1] = polar(d, 1750);
    const [x2, y2] = polar(d, d % 45 ? 1735 : 1700);
    ticks.push(<line key={d} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(95,225,255,.32)" stroke-width={d % 45 ? 1.5 : 3} />);
    if (d % 45 === 0) {
      const [tx, ty] = polar(d, 1660);
      ticks.push(
        <text key={`t${d}`} class="f-label" x={tx} y={ty} fill="rgba(147,168,194,.45)" font-family="JetBrains Mono"
          font-size="26" text-anchor="middle">{String(d).padStart(3, '0')}</text>,
      );
    }
  }
  return <>{ticks}</>;
}

/** Points scattered in a room's sector, the same every load (a seeded generator). */
function Drift({ deg }: { deg: number }) {
  let seed = deg * 7 + 3;
  const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  const points = [];
  for (let i = 0; i < 34; i++) {
    const [px, py] = polar(deg + (rnd() - 0.5) * 46, 620 + rnd() * 620);
    points.push(<circle key={i} class={i % 3 ? undefined : 'drift'} cx={px} cy={py} r={3 + rnd() * 6} fill="rgba(95,225,255,.5)" />);
  }
  return <>{points}</>;
}

function Sector({ deg, label }: { deg: number; label: string }) {
  const [x0, y0] = polar(deg - 28, 1300);
  const [x1, y1] = polar(deg + 28, 1300);
  const [lx, ly] = polar(deg, 1390);
  return (
    <>
      <path d={`M${x0} ${y0}A1300 1300 0 0 1 ${x1} ${y1}`} fill="none" stroke="rgba(95,225,255,.5)" stroke-width="5" />
      <text class="f-label" x={lx} y={ly} fill="rgba(95,225,255,.24)" font-family="Chakra Petch" font-weight="700"
        font-size="44" letter-spacing="10" text-anchor="middle">{label}</text>
      <Drift deg={deg} />
    </>
  );
}

function Sweep() {
  const [ex, ey] = polar(30, 1750);
  return (
    <g class="sweep">
      <path d={`M${C} ${C}L${C} ${C - 1750}A1750 1750 0 0 1 ${ex} ${ey}Z`} fill="url(#f-sweep)" opacity=".5" />
    </g>
  );
}

export function Field() {
  return (
    <svg viewBox={`0 0 ${FIELD} ${FIELD}`} aria-hidden="true">
      <defs>
        <pattern id="f-grid" width="80" height="80" patternUnits="userSpaceOnUse">
          <path d="M80 0H0V80" fill="none" stroke="rgba(77,163,255,.06)" />
        </pattern>
        <radialGradient id="f-core" r=".5">
          <stop offset="0" stop-color="rgba(242,180,90,.18)" />
          <stop offset=".4" stop-color="rgba(77,163,255,.06)" />
          <stop offset="1" stop-color="rgba(0,0,0,0)" />
        </radialGradient>
        <linearGradient id="f-sweep" x1="0" x2="1">
          <stop offset="0" stop-color="rgba(77,163,255,0)" />
          <stop offset="1" stop-color="rgba(95,225,255,.14)" />
        </linearGradient>
      </defs>
      <rect width={FIELD} height={FIELD} fill="url(#f-grid)" />
      <circle cx={C} cy={C} r="1200" fill="url(#f-core)" />
      <Rings />
      <Scale />
      {SECTORS.map(([deg, label]) => <Sector key={deg} deg={deg} label={label} />)}
      <Sweep />
    </svg>
  );
}
