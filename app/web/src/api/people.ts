// The people routes: the signed-in person's household's people, and granting or revoking admin.
import { ApiError, answer } from './client';
import type { PeopleResponse, Person } from './types';

/** Why a grant or revoke changed nothing, as the server's error code says. */
export type AdminRefused = 'admin_only' | 'last_admin' | 'admins_from_provider' | 'not_found';
const REFUSED: readonly string[] = ['admin_only', 'last_admin', 'admins_from_provider', 'not_found'];

function refusal(code: unknown): code is AdminRefused {
  return typeof code === 'string' && REFUSED.includes(code);
}

/** The household's people, and who decides who is an admin. */
export async function getPeople(): Promise<PeopleResponse> {
  return answer(await fetch('/api/people'), 200, 'GET /api/people');
}

/** Makes `id` an admin or not; the person as they are now, or why nothing changed. Same-origin JSON. */
export async function putAdmin(id: number, admin: boolean): Promise<Person | AdminRefused> {
  const route = 'PUT /api/people/{id}/admin';
  const response = await fetch(`/api/people/${id}/admin`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ admin }),
  });
  if (response.status === 403 || response.status === 404 || response.status === 409) {
    const body = (await response.json()) as { code?: unknown };
    if (refusal(body.code)) return body.code;
    throw new ApiError(response.status, route);
  }
  return answer(response, 200, route);
}
