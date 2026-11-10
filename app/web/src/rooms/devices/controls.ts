// The lights of the house a person may pick for a touch control.
import { signal } from '@preact/signals';
import { getCatalogue } from '../../api/connectionSettings';
import { getConnections } from '../../api/connections';
import type { CatalogueEntityInfo } from '../../api/types';

export type Lights = { state: 'loading' } | { state: 'none' } | { state: 'failed' } | { state: 'ready'; lights: CatalogueEntityInfo[] };

export const lights = signal<Lights>({ state: 'loading' });

/** Reads the lights of the household's Home Assistant, or notes it has none or could not be read. */
export async function loadLights(): Promise<void> {
  lights.value = { state: 'loading' };
  try {
    const held = (await getConnections()).connections.find((c) => c.kind === 'home_assistant');
    if (!held) {
      lights.value = { state: 'none' };
      return;
    }
    lights.value = { state: 'ready', lights: (await getCatalogue(held.id, ['light', 'scene'])).entities };
  } catch {
    lights.value = { state: 'failed' };
  }
}
