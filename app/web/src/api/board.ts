// The board's actions on an item of `GET /api/work`: cancel, pause or resume a watch, undo something she did on her own. Agreeing is
// `agree.ts`.
import { answer, ApiError } from './client';
import type { paths } from './schema';
import type { UndoDone } from './types';

type Cancelled = paths['/api/work/watches/{watch_id}']['delete']['responses'][200]['content']['application/json'];

type OnHold = paths['/api/work/watches/{watch_id}/pause']['post']['responses'][200]['content']['application/json'];

async function refusedOr<B>(response: Response, route: string): Promise<B> {
  if (response.status === 409) {
    const refused = (await response.json().catch(() => ({}))) as { code?: string };
    throw new ApiError(409, route, refused.code);
  }
  return answer(response, 200, route);
}

/** Ends watch `id` as the person. */
export async function cancelWatch(id: number): Promise<Cancelled> {
  return answer(await fetch(`/api/work/watches/${id}`, { method: 'DELETE' }), 200, 'DELETE /api/work/watches/{id}');
}

/** Pauses watch `id`: it is not checked and does not run out until it is resumed. */
export async function pauseWatch(id: number): Promise<OnHold> {
  return answer(await fetch(`/api/work/watches/${id}/pause`, { method: 'POST' }), 200, 'POST /api/work/watches/{id}/pause');
}

/** Runs the on-hold watch `id` again. */
export async function resumeWatch(id: number): Promise<OnHold> {
  return answer(await fetch(`/api/work/watches/${id}/resume`, { method: 'POST' }), 200, 'POST /api/work/watches/{id}/resume');
}

/** Takes back action `id` through her own tool for that change. A refusal (409) is an `ApiError` whose `code` is `no_undo`,
 * `already_undone` or `refused`. */
export async function undoAction(id: number): Promise<UndoDone> {
  return refusedOr(await fetch(`/api/work/actions/${id}/undo`, { method: 'POST' }), 'POST /api/work/actions/{id}/undo');
}
