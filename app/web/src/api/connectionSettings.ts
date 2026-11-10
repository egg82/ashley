// The settings of a connection: read, replace, and the catalogue its service offers for a setting to pick from.
import { answer, ApiError } from './client';
import type { ConnectionCatalogue, ConnectionSettings, ConnectionSettingsRequest, ErrorResponse, SettingsRefused } from './types';

/** Connection `id`'s settings with the schema its kind declares. A 404 is a connection with no settings, or none visible. */
export async function getSettings(id: number): Promise<ConnectionSettings> {
  return answer(await fetch(`/api/connections/${id}/settings`), 200, 'GET /api/connections/{id}/settings');
}

/** Replaces the whole of connection `id`'s settings. A 422 answers why nothing was stored; a 409 (`version_conflict`)
 * says they changed since `body.revision` was read. */
export async function putSettings(id: number, body: ConnectionSettingsRequest): Promise<ConnectionSettings | SettingsRefused> {
  const response = await fetch(`/api/connections/${id}/settings`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 422) return (await response.json()) as SettingsRefused;
  if (response.status === 409) throw new ApiError(409, 'PUT /api/connections/{id}/settings', ((await response.json()) as ErrorResponse).code);
  return answer(response, 200, 'PUT /api/connections/{id}/settings');
}

/** What connection `id`'s service has now, narrowed to `domains` (all when none). A 503 is the service not answering. */
export async function getCatalogue(id: number, domains: readonly string[]): Promise<ConnectionCatalogue> {
  const query = new URLSearchParams(domains.map((d) => ['domains', d]));
  return answer(await fetch(`/api/connections/${id}/catalogue?${query}`), 200, 'GET /api/connections/{id}/catalogue');
}
