// A person's whole-turn undo (`POST /api/benches/{bench_id}/undo-turn`), apart from `client.ts`, which `answer` comes from.
import { answer } from './client';
import type { TurnRefused, TurnUndone } from './types';

/** Takes back the whole turn of hers that made command `seq` on bench `id`, all or nothing. A refusal (409) is an answer: nothing changed. */
export async function undoTurn(id: number, seq: number): Promise<TurnUndone | TurnRefused> {
  const response = await fetch(`/api/benches/${id}/undo-turn`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ seq }),
  });
  if (response.status === 409) return (await response.json()) as TurnRefused;
  return answer(response, 200, 'POST /api/benches/{id}/undo-turn');
}
