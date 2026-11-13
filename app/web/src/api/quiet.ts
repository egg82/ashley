// The signed-in person's own quiet hours: a daily window she says nothing unprompted in.
import { ApiError, answer } from './client';
import type { QuietHours, QuietRefused } from './types';

export async function getQuiet(): Promise<QuietHours> {
  return answer(await fetch('/api/household/quiet'), 200, 'GET /api/household/quiet');
}

/** Replaces the quiet hours, null clearing them. A 422 answers what she cannot use. Same-origin JSON. */
export async function putQuiet(body: QuietHours): Promise<QuietHours | QuietRefused> {
  const response = await fetch('/api/household/quiet', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 422) {
    const refused = (await response.json()) as QuietRefused | { detail: unknown };
    if ('invalid' in refused) return refused;
    throw new ApiError(422, 'PUT /api/household/quiet');
  }
  return answer(response, 200, 'PUT /api/household/quiet');
}
