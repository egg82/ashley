// The settings sentence: which of its words are slots a person edits, and how each value reads in it.
import type { Draft } from './draft';

export type SlotField = 'timezone' | 'clock' | 'unit_system' | 'locale' | 'latitude' | 'longitude';
export type Part = { words: string } | { slot: SlotField; reads: string };

export interface Choice<V extends string> {
  value: V;
  reads: string;
}

export const CLOCKS: Choice<Draft['clock']>[] = [{ value: '24h', reads: '24-hour' }, { value: '12h', reads: '12-hour' }];
export const UNITS: Choice<Draft['unit_system']>[] = [
  { value: 'imperial', reads: 'feet and Fahrenheit' }, { value: 'metric', reads: 'metres and Celsius' },
];

const readsOf = <V extends string>(choices: Choice<V>[], value: V): string => choices.find((c) => c.value === value)?.reads ?? value;

/** The sentence for `draft`, in order. A text slot reads as what is typed, empty when nothing is. */
export function sentenceOf(draft: Draft): Part[] {
  return [
    { words: 'I keep time in ' }, { slot: 'timezone', reads: draft.timezone },
    { words: ', write ' }, { slot: 'clock', reads: readsOf(CLOCKS, draft.clock) },
    { words: ' times and use ' }, { slot: 'unit_system', reads: readsOf(UNITS, draft.unit_system) },
    { words: '. I read and write ' }, { slot: 'locale', reads: draft.locale },
    { words: '. The house is at latitude ' }, { slot: 'latitude', reads: draft.latitude },
    { words: ' and longitude ' }, { slot: 'longitude', reads: draft.longitude }, { words: '.' },
  ];
}

/** A language tag in words ("English, United States"), or null when the browser does not know it. */
export function localeGloss(tag: string): string | null {
  try {
    const { language, region } = new Intl.Locale(tag);
    const lang = new Intl.DisplayNames(['en'], { type: 'language', fallback: 'none' }).of(language);
    const where = region ? new Intl.DisplayNames(['en'], { type: 'region', fallback: 'none' }).of(region) : undefined;
    if (!lang || (region && !where)) return null;
    return where ? `${lang}, ${where}` : lang;
  } catch {
    return null;
  }
}
