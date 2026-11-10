// The Usage room's model choices as last read, and what the last change said.
import { signal } from '@preact/signals';
import { getSpendRoutes, putSpendRoute } from '../../api/spendRoutes';
import type { RouteModel, SpendRouteRefused, SpendRoutesResponse, TaskRoutes } from '../../api/types';

export type RoutesSaid = 'saved' | SpendRouteRefused['reason'] | 'failed';

export const spendRoutes = signal<SpendRoutesResponse | null>(null);
export const spendRoutesFailed = signal(false);
export const spendRoutesSaving = signal(false);
export const spendRoutesSaid = signal<RoutesSaid | null>(null);

export async function loadSpendRoutes(): Promise<void> {
  try {
    spendRoutes.value = await getSpendRoutes();
    spendRoutesFailed.value = false;
  } catch {
    spendRoutesFailed.value = true;
  }
}

/** Sets or clears the household's model for `task`; what was stored replaces what is shown. */
export async function chooseRoute(task: TaskRoutes['task'], route: RouteModel | null): Promise<void> {
  spendRoutesSaving.value = true;
  try {
    const got = await putSpendRoute(task, route);
    if ('reason' in got) {
      spendRoutesSaid.value = got.reason;
    } else {
      spendRoutes.value = got;
      spendRoutesSaid.value = 'saved';
    }
  } catch {
    spendRoutesSaid.value = 'failed';
  } finally {
    spendRoutesSaving.value = false;
  }
}
