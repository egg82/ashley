// Setting a choice row shown beside her reply by a tap on one of its options
// (`PUT /api/benches/{bench}/pieces/{piece}/choices/{name}`), apart from `client.ts`, which `answer` and `ApiError` come from.
import { answer } from './client';
import type { ChoiceSet, WireFact } from './types';

/** Sets `fact`'s row to `value`, one of its options, as the person's Edit of the piece. Any status but 200 is an
 * `ApiError` carrying it (404 the row is gone, 409 the piece changed under the tap, 422 not one of the options). */
export async function setChoice(fact: Pick<WireFact, 'bench_id' | 'piece_id' | 'name'>, value: string): Promise<ChoiceSet> {
  const route = `/api/benches/${fact.bench_id}/pieces/${fact.piece_id}/choices/${encodeURIComponent(fact.name)}`;
  const response = await fetch(route, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ value }),
  });
  return answer(response, 200, 'PUT /api/benches/{bench_id}/pieces/{piece_id}/choices/{name}');
}
