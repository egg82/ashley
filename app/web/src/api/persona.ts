// The persona routes: the household's own text for her overridable persona sections.
import { answer } from './client';
import type { PersonaDetail, PersonaEditRequest, PersonaRefusalBody, PersonaRevertRequest } from './types';

/** Every overridable section with the household's text and changelog. */
export async function getPersona(): Promise<PersonaDetail> {
  return answer(await fetch('/api/persona'), 200, 'GET /api/persona');
}

/** A change to one section: a new text, or a revert (`to_version` 0 is the shipped text). A refusal (409) is an
 * answer, not an error: nothing changed, and `reason` says why. Same-origin JSON. */
export async function changePersona(section: string, change: PersonaEditRequest | PersonaRevertRequest):
  Promise<PersonaDetail | PersonaRefusalBody> {
  const path = `/api/persona/${encodeURIComponent(section)}${'to_version' in change ? '/revert' : ''}`;
  const response = await fetch(path, {
    method: 'to_version' in change ? 'POST' : 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(change),
  });
  if (response.status === 409) return (await response.json()) as PersonaRefusalBody;
  return answer(response, 200, 'change /api/persona/{section}');
}
