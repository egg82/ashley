// A bench's kind of work and the household's skill for it, as this screen last read them. The skill is read when the
// kind changes, when its panel opens and whenever the bench is read back; a person's change to it (pin, roll back,
// approve or decline her edit) answers the skill as it then stands.
import { signal } from '@preact/signals';
import { changeSkill, getSkill, putWork, type SkillChange } from '../../../api/skills';
import type { SkillDetail, SkillRefusal } from '../../../api/types';
import { refresh } from './bench';
import { unreachable } from './benches';

/** The skill of the open bench's kind; null while none is read, or when the kind has no skill yet. */
export const skill = signal<SkillDetail | null>(null);
/** What the last change to it said, when it did not go through. */
export const trouble = signal<string | null>(null);

let reading = 0;

/** Reads the skill for `kind`; null kind (or a failed read) leaves none shown. */
export async function loadSkill(kind: string | null): Promise<void> {
  const mine = ++reading;
  if (kind === null) {
    skill.value = null;
    return;
  }
  try {
    const got = await getSkill(kind);
    if (mine === reading) skill.value = got;
  } catch (error) {
    unreachable(error);
    if (mine === reading) skill.value = null;
  }
}

/** The name a kind of work gets from its label: lowercase letters, digits and hyphens. */
export function slugOf(label: string): string {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
}

/** Sets bench `id`'s kind of work, then reads the bench back; false when it did not go through. */
export async function setWork(id: number, work: string | null, label?: string): Promise<boolean> {
  trouble.value = null;
  try {
    await putWork(id, work, label);
  } catch (error) {
    unreachable(error);
    trouble.value = "The kind of work didn't change. Try again.";
    return false;
  }
  await refresh();
  return true;
}

const REFUSED: Record<SkillRefusal['reason'], string> = {
  stale: 'She changed the method meanwhile. Look again, then try once more.',
  unchanged: 'That is the text it already has.',
  no_such_version: "That version isn't there.",
  not_proposed: "That edit isn't waiting any more.",
  bad_kind: "That isn't a name for a kind of work.",
  bad_note: "That didn't go through.",
  bad_body: "That didn't go through.",
  unknown_kind: "That isn't a kind of work.",
};

/** A person's change to the skill of `kind`; the skill as it then stands is shown, or what refused it. */
export async function change(kind: string, what: SkillChange): Promise<void> {
  trouble.value = null;
  try {
    const got = await changeSkill(kind, what);
    if ('code' in got) trouble.value = REFUSED[got.reason];
    else skill.value = got;
  } catch (error) {
    unreachable(error);
    trouble.value = "Didn't change. Can't reach Ashley, or try again.";
  }
  if (trouble.value !== null) await loadSkill(kind);
}
