// What text a persona section is in force, and whether a draft would change it.
import type { PersonaSection } from '../../api/types';

/** The text she uses for `section` now: the household's, else the shipped. */
export function inForce(section: PersonaSection): string {
  return section.override ?? section.shipped;
}

/** Whether `draft` would change what she uses, as the server judges it (surrounding space does not count). */
export function differs(section: PersonaSection, draft: string): boolean {
  return draft.trim() !== '' && draft.trim() !== inForce(section).trim();
}
