// The floor plan as data: which room each device is drawn in. Pure, so the layout is tested without a page.
import type { ListedDevice } from '../../api/types';

export type Room = { key: string; name: string; devices: ListedDevice[] };
export type Plan = {
  /** Inside the wall, in the order their first device was added. */
  rooms: Room[];
  /** The house itself, which belongs to no room. */
  whole: ListedDevice[];
  /** Outside the wall: a Discord server is reached over the internet, not from a room. */
  online: ListedDevice[];
};

/** Where a device is drawn comes from what it is wired to (`form`) and, for the rest, its `place`; never from its name. */
export function planOf(devices: ListedDevice[]): Plan {
  const rooms = new Map<string, Room>();
  const plan: Plan = { rooms: [], whole: [], online: [] };
  for (const d of devices) {
    if (d.form === 'house') plan.whole.push(d);
    else if (d.form === 'discord_server') plan.online.push(d);
    else {
      const name = d.place.trim();
      const key = name.toLowerCase();
      const room = rooms.get(key) ?? { key, name, devices: [] };
      room.devices.push(d);
      rooms.set(key, room);
    }
  }
  plan.rooms = [...rooms.values()];
  return plan;
}

/** How many places the plan draws: each room, the whole house and online, when it has a device. */
export function placeCount(plan: Plan): number {
  return plan.rooms.length + (plan.whole.length ? 1 : 0) + (plan.online.length ? 1 : 0);
}

/** The device shown first: one that takes controls, else the first drawn. */
export function firstSelected(devices: ListedDevice[]): number | null {
  return (devices.find((d) => d.takes_controls) ?? devices[0])?.id ?? null;
}
