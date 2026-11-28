// The board's actions on an item of `GET /api/work`: cancel a watch, undo something she did on her own. Agreeing is
// `agree.ts`.
import { answer, ApiError } from './client';
import type { paths } from './schema';

type Cancelled = paths['/api/work/watches/{watch_id}']['delete']['responses'][200]['content']['application/json'];

/** How an Undo stands, in `UndoDone.how` / `ActionUndone.how` of the undo route (#271). Declared here until that route is in
 * the generated schema. */
export type UndoHow = 'undoing' | 'undone' | 'waiting_on_you' | 'gone';
export interface UndoDone {
  id: number;
  how: Exclude<UndoHow, 'undoing'>;
  conversation_id: number | null;
}

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

/** Takes back action `id` through her own tool for that change. A refusal (409) is an `ApiError` whose `code` is `no_undo`,
 * `already_undone` or `refused`. */
export async function undoAction(id: number): Promise<UndoDone> {
  return refusedOr(await fetch(`/api/work/actions/${id}/undo`, { method: 'POST' }), 'POST /api/work/actions/{id}/undo');
}
