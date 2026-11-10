// The Usage room's model choices: which model carries each chat-facing task for the signed-in person's household.
import { ApiError, answer } from './client';
import type { RouteModel, SpendRouteRefused, SpendRoutesResponse, TaskRoutes } from './types';

/** Every task the household may choose a model for, then the action judge, shown read-only. */
export async function getSpendRoutes(): Promise<SpendRoutesResponse> {
  return answer(await fetch('/api/spend/routes'), 200, 'GET /api/spend/routes');
}

/** Sets the household's model for `task`, or clears it with null. A 422 answers why it cannot. Same-origin JSON. */
export async function putSpendRoute(task: TaskRoutes['task'], route: RouteModel | null): Promise<SpendRoutesResponse | SpendRouteRefused> {
  const where = `PUT /api/spend/routes/${task}`;
  const response = await fetch(`/api/spend/routes/${encodeURIComponent(task)}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ route }),
  });
  if (response.status === 422) {
    const refused = (await response.json()) as SpendRouteRefused | { detail: unknown };
    if ('reason' in refused) return refused;
    throw new ApiError(422, where);
  }
  return answer(response, 200, where);
}
