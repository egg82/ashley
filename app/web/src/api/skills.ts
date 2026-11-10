// The skill routes: a bench's kind of work, and the household's skill for a kind with what a person can do to it.
import { answer } from './client';
import type { BenchSummary, SkillDetail, SkillRefusal } from './types';

/** Sets bench `id`'s kind of work (null clears it); `label` names a kind the household has not started. Answers the bench. */
export async function putWork(id: number, work: string | null, label?: string): Promise<BenchSummary> {
  const response = await fetch(`/api/benches/${id}/work`, {
    method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ work, label }) });
  return answer(response, 200, 'PUT /api/benches/{id}/work');
}

/** The household's skill for `kind` with its changelog; null when there is none yet. */
export async function getSkill(kind: string): Promise<SkillDetail | null> {
  const response = await fetch(`/api/skills/${encodeURIComponent(kind)}`);
  if (response.status === 404) return null;
  return answer(response, 200, 'GET /api/skills/{kind}');
}

/** What a person does to a skill: pin or unpin it, roll it back to a version, or approve or decline her waiting edit. */
export type SkillChange = { pin: boolean } | { rollbackTo: number } | { version: number; approve: boolean };

/** A change to a skill by a person. A refusal (409) is an answer, not an error: nothing changed, and `reason` says why. */
export async function changeSkill(kind: string, change: SkillChange): Promise<SkillDetail | SkillRefusal> {
  const base = `/api/skills/${encodeURIComponent(kind)}`;
  const json = { 'content-type': 'application/json' };
  let response: Response;
  if ('pin' in change) {
    response = await fetch(`${base}/pin`, { method: 'PUT', headers: json, body: JSON.stringify({ pinned: change.pin }) });
  } else if ('rollbackTo' in change) {
    response = await fetch(`${base}/rollback`, { method: 'POST', headers: json, body: JSON.stringify({ to_version: change.rollbackTo }) });
  } else {
    response = await fetch(`${base}/proposals/${change.version}/${change.approve ? 'approve' : 'decline'}`, { method: 'POST' });
  }
  if (response.status === 409) return (await response.json()) as SkillRefusal;
  return answer(response, 200, 'change /api/skills/{kind}');
}
