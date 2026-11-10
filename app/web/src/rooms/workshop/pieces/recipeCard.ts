import type { BenchPiece } from '../../../api/types';

type Recipe = NonNullable<BenchPiece['recipe']>;

export type Card = {
  name: string;
  /** The page it came from, or null when the address is not https (the server checks; the page does not trust it). */
  source: URL | null;
  /** How much it makes and for whom, in the words a cook reads. */
  makes: string;
  /** Prep, cook and total time, each only when the page gives it; empty when it gives none. */
  times: string;
  /** Each ingredient as shown: scaled by the server when it could be, else as the page wrote it and marked so. */
  ingredients: { text: string; asWritten: boolean }[];
  steps: string[];
  /** Said over the steps when the amounts were scaled, since steps keep the page's own numbers. */
  stepsNote: string;
};

/** Minutes as hours and minutes. */
export function minutes(total: number): string {
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

function httpsUrl(text: string): URL | null {
  try {
    const url = new URL(text);
    return url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

function makesOf(r: Recipe): string {
  const said = r.yield_text || 'not given';
  if (r.serves === null) return `Makes ${said}, as written`;
  if (r.factor === null) return `For ${r.serves}, not scaled: the page gives no count (${said})`;
  return `For ${r.serves}, scaled from ${r.makes} (the page says ${said})`;
}

/** What a recipe card shows, from the server's understanding of the piece. Amounts are never worked out here. */
export function recipeCard(r: Recipe): Card {
  const scaled = r.factor !== null;
  const said: [string, number | null][] = [['Prep', r.prep_min], ['Cook', r.cook_min], ['Total', r.total_min]];
  const times = said.flatMap(([label, m]) => (m === null ? [] : [`${label} ${minutes(m)}`])).join(' · ');
  return {
    name: r.name,
    source: httpsUrl(r.url),
    makes: makesOf(r),
    times,
    ingredients: r.ingredients.map((line) => ({ text: line.shown, asWritten: scaled && !line.scaled })),
    steps: r.steps,
    stepsNote: scaled ? `As the page wrote them, for ${r.makes}` : '',
  };
}
