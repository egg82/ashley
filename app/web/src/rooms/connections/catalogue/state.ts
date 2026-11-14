// The catalogue page's state: the providers as last read, and the models of each provider opened so far (one read per
// provider, never per model).
import { signal } from '@preact/signals';
import { getCatalogue, getCatalogueModels } from '../../../api/catalogue';
import { ApiError } from '../../../api/client';
import type { ModelCatalogueModel, ModelCatalogueResponse } from '../../../api/types';

/** `denied`: not an admin of the deployment (403); `unreachable`: a 503 or no answer at all. */
export type Overview =
  | { state: 'loading' | 'denied' | 'unreachable' | 'failed' }
  | { state: 'ready'; catalogue: ModelCatalogueResponse };
export type Listing = 'loading' | 'failed' | readonly ModelCatalogueModel[];

export const overview = signal<Overview>({ state: 'loading' });
export const listings = signal<Readonly<Record<string, Listing>>>({});

function failure(error: unknown): 'denied' | 'unreachable' | 'failed' {
  if (error instanceof ApiError && error.status === 403) return 'denied';
  return !(error instanceof ApiError) || error.status === 503 ? 'unreachable' : 'failed';
}

export async function loadCatalogue(): Promise<void> {
  overview.value = { state: 'loading' };
  try {
    overview.value = { state: 'ready', catalogue: await getCatalogue() };
  } catch (error) {
    overview.value = { state: failure(error) };
  }
}

/** Reads `provider`'s models unless they are read or being read. */
export async function loadModels(provider: string): Promise<void> {
  const had = listings.value[provider];
  if (had === 'loading' || (had !== undefined && had !== 'failed')) return;
  listings.value = { ...listings.value, [provider]: 'loading' };
  let next: Listing;
  try {
    next = (await getCatalogueModels(provider)).models;
  } catch {
    next = 'failed';
  }
  listings.value = { ...listings.value, [provider]: next };
}
