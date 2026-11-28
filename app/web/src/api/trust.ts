// What she may just do: the signed-in person's own choice per kind of action, read and replaced whole. A 409 means
// the choices changed since the revision sent; callers read `ApiError.status`.
import { answer } from './client';
import type { TrustRow, TrustSettings } from './types';

export async function getTrust(): Promise<TrustSettings> {
  return answer(await fetch('/api/trust'), 200, 'GET /api/trust');
}

export async function putTrust(revision: number, picks: { kind: string; value: TrustRow['value'] }[]): Promise<TrustSettings> {
  const response = await fetch('/api/trust', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ revision, picks }),
  });
  return answer(response, 200, 'PUT /api/trust');
}
