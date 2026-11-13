// The model catalogue's providers, which an admin picks an OpenAI-compatible provider from.
import { answer } from './client';
import type { ModelCatalogueResponse } from './types';

/** Every provider the catalogue lists, each with its OpenAI-compatible base URL where it has one. Admin only (403). */
export async function getCatalogue(): Promise<ModelCatalogueResponse> {
  return answer(await fetch('/api/catalogue'), 200, 'GET /api/catalogue');
}
