// Agreeing to a held change by a tap (`POST /api/chat/agree`), apart from `client.ts`, which `answer` and `ApiError` come from.
import { answer, ApiError } from './client';
import type { AgreeReply, AgreeRequest } from './types';

/** Agrees to the held proposal `body.proposal_id`: carries out what it held, no model asked; answers what became of each call. A
 * refusal (409) is an `ApiError` whose `code` is `gone`, `expired` or `not_yours`. Same-origin JSON. */
export async function agreeTo(body: AgreeRequest): Promise<AgreeReply> {
  const response = await fetch('/api/chat/agree', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status === 409) {
    const refused = (await response.json().catch(() => ({}))) as { code?: string };
    throw new ApiError(409, 'POST /api/chat/agree', refused.code);
  }
  return answer(response, 200, 'POST /api/chat/agree');
}
