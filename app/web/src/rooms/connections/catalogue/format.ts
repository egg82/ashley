// How the catalogue page writes what the catalogue knows. A value the catalogue does not hold comes back null, never a
// zero, and the page draws it as unknown; a price of 0 is only ever a price upstream listed.
import { locale } from '../../../household/format.ts';
import type { ModelCatalogueModel, ModelCatalogueProvider } from '../../../api/types.ts';

const COMPACT = (n: number) => new Intl.NumberFormat(locale(), { notation: 'compact', maximumFractionDigits: 1 }).format(n);

/** USD per million tokens, as listed: "$3", "$0.075". */
export function perMtok(usd: number | null): string | null {
  return usd === null ? null : `$${String(Number(usd.toFixed(6)))}`;
}

/** A token count: "200K", "1M". */
export function tokenCount(n: number | null): string | null {
  return n === null ? null : COMPACT(n);
}

export function yesNo(value: boolean | null): string | null {
  return value === null ? null : value ? 'yes' : 'no';
}

/** What a model's price status says, or null when it needs no word (`priced`). */
export function priceWord(status: ModelCatalogueModel['price']['status']): string | null {
  switch (status) {
    case 'priced': return null;
    case 'unpriced': return 'unpriced';
    case 'listed_zero': return 'listed at $0';
    case 'free': return 'free';
    case 'local': return 'local, no cost';
  }
}

/** Providers the deployment is connected to first, then the rest by name, keeping those whose name or id holds `query`. */
export function orderProviders(providers: readonly ModelCatalogueProvider[], query: string): ModelCatalogueProvider[] {
  const q = query.trim().toLowerCase();
  const kept = providers.filter((p) => q === '' || p.name.toLowerCase().includes(q) || p.provider.toLowerCase().includes(q));
  return [...kept].sort((a, b) => Number(b.has_connection === true) - Number(a.has_connection === true) || a.name.localeCompare(b.name));
}

/** How many of `providers` are connected, or null when none could be told (the connections could not be read). */
export function connectedCount(providers: readonly ModelCatalogueProvider[]): number | null {
  return providers.some((p) => p.has_connection !== null) ? providers.filter((p) => p.has_connection === true).length : null;
}

/** The refresh cadence, "every 6 h" or "every 10 min". */
export function cadence(seconds: number): string {
  const hours = seconds / 3600;
  return hours >= 1 ? `every ${Number(hours.toFixed(1))} h` : `every ${Math.max(1, Math.round(seconds / 60))} min`;
}

export function when(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));
}

/** Models shown before "Show all": a provider can list hundreds. */
export const SHOWN = 40;
