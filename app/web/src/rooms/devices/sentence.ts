// Each device in a sentence, and the words the plan's marks stand for.
import type { ListedDevice } from '../../api/types';

export type Sentence = { name: string; before: string; who: string; after: string };

const WHO: Record<ListedDevice['audience'], string> = { owner: 'its owner alone', household: 'all of you', present: 'whoever is there' };
const WHO_MARK: Record<ListedDevice['audience'], string> = { owner: "One person's", household: 'Shared by the household', present: "Whoever's there" };
const KIND: Record<ListedDevice['form'], string> = { satellite: 'Voice satellite', discord_server: 'Discord server', house: 'The house itself', other: 'Other kind' };

export const whoMark = (a: ListedDevice['audience']): string => WHO_MARK[a];
export const kindName = (f: ListedDevice['form']): string => KIND[f];
export const itDoes = (d: ListedDevice): string => (d.medium === 'spoken' ? 'Hears and speaks' : 'Shows text');

/** "In the hallway": a place's name as a heading. */
export function inPlace(name: string): string {
  return `In the ${name.trim()}`;
}

/** The one sentence a device's row reads as; `who` is the part the audience mark stands for. */
export function sentenceOf(d: ListedDevice): Sentence {
  const who = WHO[d.audience];
  const heard = d.medium === 'spoken';
  if (d.form === 'house') return { name: d.name, before: ', your house itself. It hands her wake-ups, and she reads and writes with ', who, after: '.' };
  if (d.form === 'discord_server') return { name: d.name, before: ', a Discord server she reads and writes in with ', who, after: '.' };
  if (d.form === 'satellite') return { name: d.name, before: ', a voice satellite that hears and answers ', who, after: '.' };
  if (d.takes_controls) return { name: d.name, before: ', a screen ', who, after: ' can read and tap.' };
  return { name: d.name, before: heard ? ', a device that hears and answers ' : ', a device that reads and writes with ', who, after: '.' };
}
