// The connections routes: list, add, replace, rename and remove, each connection addressed by its id.
import { answer, ApiError } from './client';
import type {
  ConnectionRefused, ConnectionResource, ConnectionsResponse, ConnectionRequest, ErrorResponse, HouseholdConnection, NewConnectionRequest,
  OAuthStartRequest, OAuthStartResponse,
} from './types';

/** The signed-in person's household's connections, and whether any can be added here. */
export async function getConnections(): Promise<ConnectionsResponse> {
  return answer(await fetch('/api/connections'), 200, 'GET /api/connections');
}

/** Adds a connection; a 400 answers why nothing was stored, a 409 why the owner cannot hold another, a 422 a label or
 * catalogue provider the kind does not take (`ApiError.code`: `bad_label`, `unsupported`). */
export async function addConnection(body: NewConnectionRequest): Promise<HouseholdConnection | ConnectionRefused> {
  const response = await fetch('/api/connections', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 400) return (await response.json()) as ConnectionRefused;
  if (response.status === 409 || response.status === 422) {
    throw new ApiError(response.status, 'POST /api/connections', ((await response.json()) as Partial<ErrorResponse>).code);
  }
  return answer(response, 201, 'POST /api/connections');
}

/** Gives connection `id` a new address and key or token; a 400 answers why nothing was stored. */
export async function replaceConnection(id: number, body: ConnectionRequest): Promise<HouseholdConnection | ConnectionRefused> {
  const response = await fetch(`/api/connections/${id}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 400) return (await response.json()) as ConnectionRefused;
  return answer(response, 200, 'PUT /api/connections/{id}');
}

/** Renames connection `id`; a 409 means the owner already uses that label for the kind, a 422 `bad_label` that the kind
 * does not take it. */
export async function relabelConnection(id: number, label: string): Promise<HouseholdConnection> {
  const response = await fetch(`/api/connections/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ label }),
  });
  if (response.status === 409 || response.status === 422) {
    throw new ApiError(response.status, 'PATCH /api/connections/{id}', ((await response.json()) as Partial<ErrorResponse>).code);
  }
  return answer(response, 200, 'PATCH /api/connections/{id}');
}

/** Hands connection `id` to the household, or takes it back as the signed-in person's own (`holder` `person`). A 403 is a
 * take-back by someone who did not add it, a 409 a label the new holder already uses (`label_taken`) or a kind it already holds as many of as it allows (`too_many`). */
export async function moveConnection(id: number, holder: 'household' | 'person'): Promise<HouseholdConnection> {
  const response = await fetch(`/api/connections/${id}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ holder }),
  });
  if (response.status === 403 || response.status === 409) {
    throw new ApiError(response.status, 'PATCH /api/connections/{id}', ((await response.json()) as ErrorResponse).code);
  }
  return answer(response, 200, 'PATCH /api/connections/{id}');
}

/** Shares resource `ref` of connection `id` with the household, or keeps it for the owner (`shared` false). A 409 is a household connection's resource, which is always shared. */
export async function shareResource(id: number, ref: string, shared: boolean): Promise<ConnectionResource> {
  const response = await fetch(`/api/connections/${id}/resources/${encodeURIComponent(ref)}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ shared }),
  });
  if (response.status === 409) throw new ApiError(409, 'PATCH /api/connections/{id}/resources/{ref}', ((await response.json()) as ErrorResponse).code);
  return answer(response, 200, 'PATCH /api/connections/{id}/resources/{ref}');
}

/** Removes connection `id`. */
export async function disconnectConnection(id: number): Promise<void> {
  const response = await fetch(`/api/connections/${id}`, { method: 'DELETE' });
  if (response.status !== 204) throw new ApiError(response.status, 'DELETE /api/connections/{id}');
}

/** Starts connecting an OAuth kind at `provider`; answers the consent page to send the browser to. A 404 is a kind that provider does not serve, a 503 a provider not set up here. */
export async function startOAuthConnect(provider: string, body: OAuthStartRequest): Promise<OAuthStartResponse> {
  const response = await fetch(`/api/connections/oauth/${encodeURIComponent(provider)}/start`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return answer(response, 201, 'POST /api/connections/oauth/{provider}/start');
}
