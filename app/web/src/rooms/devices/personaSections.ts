// The household's persona sections as last read, and what the last change came to.
import { signal } from '@preact/signals';
import { changePersona, getPersona } from '../../api/persona';
import type { PersonaDetail, PersonaRefusalBody, PersonaSection } from '../../api/types';

export type PersonaLoad = 'loading' | 'ready' | 'failed';
export type PersonaSaid = PersonaRefusalBody['reason'] | 'saved' | 'reverted' | 'failed';

export const persona = signal<PersonaDetail | null>(null);
export const personaState = signal<PersonaLoad>('loading');
/** What the last change to a section came to; null when there is nothing to say. */
export const personaSaid = signal<{ section: string; said: PersonaSaid } | null>(null);

export async function loadPersona(): Promise<void> {
  personaState.value = 'loading';
  try {
    persona.value = await getPersona();
    personaState.value = 'ready';
  } catch {
    personaState.value = 'failed';
  }
}

async function change(section: PersonaSection, body: Parameters<typeof changePersona>[1], ok: PersonaSaid): Promise<boolean> {
  personaSaid.value = null;
  try {
    const got = await changePersona(section.section, body);
    if ('reason' in got) {
      personaSaid.value = { section: section.section, said: got.reason };
      if (got.reason === 'stale') await loadPersona();
      return false;
    }
    persona.value = got;
    personaSaid.value = { section: section.section, said: ok };
    return true;
  } catch {
    personaSaid.value = { section: section.section, said: 'failed' };
    return false;
  }
}

/** Makes `body` the household's text for `section`; whether it was stored. */
export function savePersona(section: PersonaSection, body: string, why: string): Promise<boolean> {
  return change(section, { body, why, base_version: section.persona_version }, 'saved');
}

/** Brings back version `to` of `section` (0: the shipped text); whether it was stored. */
export function revertPersona(section: PersonaSection, to: number, why: string): Promise<boolean> {
  return change(section, { to_version: to, why, base_version: section.persona_version }, 'reverted');
}
