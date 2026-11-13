// The letter above the ledger: a few sentences written from the payload and nothing else. Every figure in it is one the
// report holds; what the report does not know is said as not known, never as a zero.
import type { SpendBalance, SpendProvider, SpendResponse } from '../../api/types';
import { leftOut, spanOf, usdOf } from './certainty.ts';
import { callsOf, count, day, money } from './format.ts';
import { taskName } from './routeChoice.ts';
import { sumTotals } from './totals.ts';
import { whenOf, type Win } from './window.ts';

/** A stretch of the letter; `fig` marks a figure drawn from the payload. */
export interface Run {
  text: string;
  fig?: boolean;
}
export type Paragraph = Run[];

const t = (text: string): Run => ({ text });
const f = (text: string): Run => ({ text, fig: true });

function leftOutSentence(unpriced: number, noUsage: number): Run[] {
  const them = unpriced + noUsage === 1 ? 'it is' : 'they are';
  const unp = `${callsOf(unpriced)} ${unpriced === 1 ? 'has' : 'have'} no known price`;
  const nou = `${callsOf(noUsage)} reported no usage`;
  const what = unpriced > 0 && noUsage > 0 ? `${unp} and ${nou}` : unpriced > 0 ? unp : nou;
  return [t(` ${what}, so ${them} not in that figure.`)];
}

function totalParagraph(s: SpendResponse, win: Win): Paragraph {
  const total = sumTotals(s.providers.map((p) => p.usage[win]));
  const span = spanOf(total);
  const when = whenOf(win);
  switch (span.kind) {
    case 'idle':
      return [t(`She made no calls ${when}.`)];
    case 'noUsage':
      return [t('She made '), f(callsOf(total.calls)), t(` ${when}, and none reported what it used, so there is no cost to give.`)];
    case 'unpriced':
      return [t('She made '), f(callsOf(total.calls)), t(` ${when}, but none has a known price, so there is no cost to add up.`)];
    case 'measured':
      return [t(`Her calls ${when} cost the household `), f(money(span.usd)), t(', across '), f(callsOf(total.calls)), t('.')];
    case 'partial':
      return [
        t(`Her calls ${when} cost the household at least `), f(money(span.usd)), t(', across '), f(callsOf(total.calls)), t('.'),
        ...leftOutSentence(span.unpriced, span.noUsage),
      ];
  }
}

/** The shares of a total, by what carries them. */
function topOf<K>(parts: Map<K, number>): [K, number] | null {
  let top: [K, number] | null = null;
  for (const e of parts) if (!top || e[1] > top[1]) top = e;
  return top;
}

function shareParagraph(s: SpendResponse, win: Win): Paragraph | null {
  const costed = s.providers.map((p) => ({ p, usd: usdOf(spanOf(p.usage[win])) })).filter((x): x is { p: SpendProvider; usd: number } => x.usd !== null && x.usd > 0);
  const total = costed.reduce((a, x) => a + x.usd, 0);
  if (total <= 0) return null;
  const topProvider = topOf(new Map(costed.map((x) => [x.p.label, x.usd])))!;
  const share = topProvider[1] / total;
  const first: Run[] = share >= 1
    ? [f(topProvider[0]), t(' took all of it.')]
    : [f(topProvider[0]), t(' took '), f(`${Math.min(99, Math.round(share * 100))}%`), t(' of it.')];
  const byTask = new Map<string, number>();
  const gaps = new Map<string, number>();
  for (const p of s.providers) {
    for (const k of p.tasks) {
      const sp = spanOf(k.usage[win]);
      const usd = usdOf(sp);
      if (usd !== null) byTask.set(k.task, (byTask.get(k.task) ?? 0) + usd);
      const out = leftOut(sp);
      gaps.set(k.task, (gaps.get(k.task) ?? 0) + out.unpriced + out.noUsage);
    }
  }
  const topTask = byTask.size > 1 ? topOf(byTask) : null;
  if (!topTask) return first;
  const bound = (gaps.get(topTask[0]) ?? 0) > 0 ? 'at least ' : '';
  return [...first, t(' '), f(taskName(topTask[0])), t(` alone was ${bound}`), f(money(topTask[1])), t('.')];
}

const known = (b: SpendBalance) => b.state === 'read' && b.quota !== null;

function balanceParagraph(s: SpendResponse): Paragraph | null {
  const paid = s.providers.filter((p) => p.kind === 'paid');
  if (paid.length === 0) return null;
  const read = paid.filter((p) => known(p.balance));
  const failed = paid.filter((p) => p.balance.state === 'failed');
  const unsaid = paid.filter((p) => p.balance.state === 'unknown');
  const out: Paragraph = [];
  for (const p of read) {
    const q = p.balance.quota!;
    out.push(f(p.label), t(' has '), f(`${count(q.remaining)} ${q.unit}`), t(q.resets_at ? ` left until ${day(q.resets_at, s.zone)}. ` : ' left. '));
  }
  if (unsaid.length > 0) {
    const n = unsaid.length;
    if (n === 1) out.push(t(read.length > 0 ? 'The other paid provider doesn’t say what is left. ' : 'The paid provider doesn’t say what is left. '));
    else if (read.length > 0) out.push(t('The other '), f(count(n)), t(' paid providers don’t say what is left. '));
    else out.push(t('None of the '), f(count(n)), t(' paid providers says what is left. '));
  }
  if (failed.length > 0) {
    out.push(t(`Couldn’t read what ${failed.map((p) => p.label).join(' and ')} ${failed.length === 1 ? 'has' : 'have'} left.`));
  }
  if (out.length === 0) return null;
  const last = out[out.length - 1]!;
  out[out.length - 1] = { ...last, text: last.text.trimEnd() };
  return out;
}

/** The letter for a window, a paragraph per thing it says; a paragraph with nothing to say is left out. */
export function letterOf(s: SpendResponse, win: Win): Paragraph[] {
  return [totalParagraph(s, win), shareParagraph(s, win), balanceParagraph(s)].filter((p): p is Paragraph => p !== null);
}
