// How the Usage room writes a number. A value the server did not give is never written as a zero: callers branch on null.
import type { SpendTotals } from '../../api/types';
import { hour, locale } from '../../household/format.ts';

const COUNT = (n: number) => new Intl.NumberFormat(locale()).format(n);
const COMPACT = (n: number) => new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }).format(n);

export function count(n: number): string {
  return COUNT(n);
}

export function callsOf(n: number): string {
  return `${count(n)} ${n === 1 ? 'call' : 'calls'}`;
}

export function tokens(n: number): string {
  return n < 10_000 ? COUNT(n) : COMPACT(n);
}

/** Dollars, to the cent from a dollar up and finer below, so a cheap call is not "$0.00". */
export function money(usd: number): string {
  const sign = usd < 0 ? '-' : '';
  const v = Math.abs(usd);
  if (v >= 100) return `${sign}$${COUNT(Math.round(v))}`;
  if (v >= 1 || v === 0) return `${sign}$${v.toFixed(2)}`;
  return `${sign}$${v < 0.01 ? v.toFixed(4) : v.toFixed(3)}`;
}

/** A cost to the digit the ledger holds it, for the detail a person asks for. */
export function exactMoney(usd: number): string {
  return `$${String(Number(usd.toFixed(8)))}`;
}

/** What was used, from only the calls that reported it. */
export function usedLine(t: SpendTotals): string {
  const parts = [callsOf(t.calls)];
  if (t.input_tokens !== null && t.output_tokens !== null && t.input_tokens + t.output_tokens > 0) {
    parts.push(`${tokens(t.input_tokens)} in`, `${tokens(t.output_tokens)} out`);
  }
  if (t.characters) parts.push(`${tokens(t.characters)} chars`);
  if (t.audio_ms) parts.push(`${Math.round(t.audio_ms / 1000)} s audio`);
  return parts.join(' · ');
}

/** The time of day, in the household's zone and clock. */
export function timeOf(iso: string, zone: string): string {
  return new Intl.DateTimeFormat(locale(), { hour: hour(), minute: '2-digit', timeZone: zone }).format(new Date(iso));
}

/** "2 min ago", or the time of day once it is over an hour old. */
export function ago(iso: string, now: Date, zone: string): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `at ${timeOf(iso, zone)}`;
}

export function day(iso: string, zone: string): string {
  return new Intl.DateTimeFormat(locale(), { month: 'short', day: 'numeric', timeZone: zone }).format(new Date(iso));
}
