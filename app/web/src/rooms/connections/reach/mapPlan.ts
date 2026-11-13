// Where everything sits on the reach map: the household's hub and the person's, each connection a node on its holder's
// hub, and a ghost node for each offered kind not yet held. Pure over the payloads, so what goes where is tested without a
// browser. Coordinates are in a viewBox that grows with the number of rings.
import type { ConnectionKindInfo, HouseholdConnection } from '../../../api/types';
import { ageShort, bandOf, type Band } from './answered.ts';
import { needOf } from './needs.ts';
import type { Tooth } from './teeth.ts';
import { teethOf } from './teeth.ts';

export type HubId = 'household' | 'person';

export interface MapNode {
  key: string;
  /** The connection's id; null for a ghost, which is a kind that could be added. */
  id: number | null;
  kind: string;
  title: string;
  hub: HubId;
  x: number;
  y: number;
  ghost: boolean;
  band: Band | null;
  age: string | null;
  needs: boolean;
  teeth: Tooth[];
  /** Where its label goes: beside it on the outer side where nodes are stacked, else under it. */
  side: 'left' | 'right' | 'below';
}

export interface Hub {
  id: HubId;
  x: number;
  y: number;
  label: string;
  sub: string;
}

export interface MapPlan {
  w: number;
  h: number;
  hubs: Hub[];
  nodes: MapNode[];
}

export const NODE_R = 22;
export const HUB_R = 40;
const RX = 190;
const RY = 112;
const STEP_X = 64;
const STEP_Y = 62;
const PER_RING = 8;
const GAP_DEG = 60;
const SIDE_AT = 0.55;

type Draft = Omit<MapNode, 'x' | 'y' | 'side'>;

function ringsOf(n: number): number {
  return Math.max(1, Math.ceil(n / PER_RING));
}

/** Spreads `drafts` on rings around (`cx`, `cy`), leaving a gap of `GAP_DEG` either side of `facing` (towards the other hub). */
function around(drafts: Draft[], cx: number, cy: number, facing: number): MapNode[] {
  return drafts.map((d, i) => {
    const ring = Math.floor(i / PER_RING);
    const onRing = drafts.slice(ring * PER_RING, (ring + 1) * PER_RING).length;
    const slot = i - ring * PER_RING + 0.5 + (ring % 2) * 0.5;
    const angle = ((facing + GAP_DEG + ((360 - 2 * GAP_DEG) * slot) / (onRing + (ring % 2) * 0.5)) * Math.PI) / 180;
    const cos = Math.cos(angle);
    const side = Math.abs(cos) < SIDE_AT ? 'below' : cos < 0 ? 'left' : 'right';
    return { ...d, side, x: Math.round(cx + (RX + ring * STEP_X) * cos), y: Math.round(cy + (RY + ring * STEP_Y) * Math.sin(angle)) };
  });
}

function ghostHub(kind: ConnectionKindInfo): HubId {
  return kind.holders.includes('person') ? 'person' : 'household';
}

function draftOf(c: HouseholdConnection, kind: ConnectionKindInfo | undefined, now: number): Draft {
  return {
    key: `c${c.id}`, id: c.id, kind: c.kind, title: c.label || kind?.title || c.kind, hub: c.personal ? 'person' : 'household', ghost: false,
    band: bandOf(c.checked_at, now), age: ageShort(c.checked_at, now), needs: kind !== undefined && needOf(c, kind) !== null, teeth: teethOf(c),
  };
}

function ghostOf(kind: ConnectionKindInfo): Draft {
  return { key: `k${kind.name}`, id: null, kind: kind.name, title: kind.title, hub: ghostHub(kind), ghost: true, band: null, age: null, needs: false, teeth: [] };
}

/** `person` names the signed-in person for their hub. */
export function planOf(
  connections: readonly HouseholdConnection[],
  kinds: readonly ConnectionKindInfo[],
  now: number,
  person: string,
): MapPlan {
  const held = connections.map((c) => draftOf(c, kinds.find((k) => k.name === c.kind), now));
  const ghosts = kinds.filter((k) => connections.filter((c) => c.kind === k.name).length < k.most).map(ghostOf);
  const all = [...held, ...ghosts];
  const mine = all.filter((d) => d.hub === 'person');
  const house = all.filter((d) => d.hub === 'household');
  const rings = Math.max(ringsOf(mine.length), ringsOf(house.length)) - 1;
  const padX = rings * STEP_X;
  const padY = rings * STEP_Y;
  const cy = 184 + padY;
  const hx = 340 + padX;
  const px = 660 + padX;
  return {
    w: 1000 + 2 * padX,
    h: 368 + 2 * padY,
    hubs: [
      { id: 'household', x: hx, y: cy, label: 'Household', sub: `${held.filter((d) => d.hub === 'household').length} held together` },
      { id: 'person', x: px, y: cy, label: person, sub: `chats that are ${person}’s alone` },
    ],
    nodes: [...around(house, hx, cy, 0), ...around(mine, px, cy, 180)],
  };
}
