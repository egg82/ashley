// A person's house routes: the household's lights and scenes, pressed from a signed-in screen, and the house at a glance.
import { answer } from './client';
import type { paths } from './schema';
import type { HouseGlance, KioskControl } from './types';

type ControlDone = paths['/api/house/controls/{name}']['post']['responses'][200]['content']['application/json'];

/** The household's lights and scenes, each light with whether it is on (null when the house could not say). */
export async function getHouseControls(): Promise<KioskControl[]> {
  return (await answer<{ controls: KioskControl[] }>(await fetch('/api/house/controls'), 200, 'GET /api/house/controls')).controls;
}

/** Presses control `name` as the person; whether her tool reported it done. A 429 is the person's rate. */
export async function pressHouseControl(name: string): Promise<boolean> {
  const response = await fetch(`/api/house/controls/${encodeURIComponent(name)}`, { method: 'POST' });
  return (await answer<ControlDone>(response, 200, 'POST /api/house/controls/{name}')).done;
}

/** Who is home and what needs the person; a part that cannot be read is null. */
export async function getHouseGlance(): Promise<HouseGlance> {
  return answer(await fetch('/api/house/glance'), 200, 'GET /api/house/glance');
}
