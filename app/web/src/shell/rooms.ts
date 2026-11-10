// Where each room sits on the field. Her rooms are on a circle around her at a compass bearing; sign-in is the same
// centre seen close up, so leaving it is a pure zoom out.

export type RoomId = 'signin' | 'her' | 'memory' | 'workshop' | 'devices' | 'connections' | 'spend';
export type NavRoomId = Exclude<RoomId, 'signin'>;

export interface Room {
  /** Field coordinates of the room's centre, in the field's 4000-unit space. */
  at: readonly [number, number];
  /** Camera zoom while the room is shown. */
  z: number;
}

export interface NavRoom extends Room {
  id: NavRoomId;
  path: string;
  /** Compass bearing from her, as the nav prints it. */
  bearing: string;
  label: string;
}

export const FIELD = 4000;
export const CENTRE = FIELD / 2;
const RING = 1100;

/** A point `r` from the centre at compass bearing `deg` (0 is up, clockwise). */
export function polar(deg: number, r: number): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [CENTRE + r * Math.sin(rad), CENTRE - r * Math.cos(rad)];
}

function nav(id: NavRoomId, path: string, deg: number, label: string): NavRoom {
  const at: [number, number] = deg === 0 ? [CENTRE, CENTRE] : polar(deg, RING);
  return { id, path, at, z: 1, bearing: String(deg).padStart(3, '0'), label };
}

export const NAV: readonly NavRoom[] = [
  nav('her', '/', 0, 'Ashley'),
  nav('memory', '/memory', 315, 'Memory'),
  nav('workshop', '/workshop', 180, 'Workshop'),
  nav('devices', '/devices', 70, 'Devices'),
  nav('spend', '/usage', 125, 'Usage'),
  nav('connections', '/connections', 250, 'Connections'),
];

export const SIGNIN: Room = { at: [CENTRE, CENTRE], z: 2.4 };

export function room(id: RoomId): Room {
  return id === 'signin' ? SIGNIN : NAV.find((r) => r.id === id)!;
}

/** The room a path names, its own or one under it (`/workshop/12`); any path no room claims opens her room. */
export function roomForPath(path: string): NavRoom {
  return NAV.find((r) => r.path === path || (r.path !== '/' && path.startsWith(`${r.path}/`))) ?? NAV[0]!;
}

/** The bench a path names (`/workshop/<id>`), or null. */
export function benchOf(path: string): number | null {
  const m = /^\/workshop\/(\d+)\/?$/.exec(path);
  return m ? Number(m[1]) : null;
}

/** The connection whose settings a path names (`/connections/<id>/settings`), or null. */
export function settingsOf(path: string): number | null {
  const m = /^\/connections\/(\d+)\/settings\/?$/.exec(path);
  return m ? Number(m[1]) : null;
}

/** The path of room `id`, or of bench `bench` in the workshop. */
export function pathTo(id: NavRoomId, bench: number | null): string {
  return bench === null ? NAV.find((r) => r.id === id)!.path : `/workshop/${bench}`;
}

/** Whether `path` is one of the rooms' own routes: a room, or a bench. */
export function isRoomPath(path: string): boolean {
  return NAV.some((r) => r.path === path) || benchOf(path) !== null;
}
