// The model catalogue's routes, admin only (403): the providers it lists, which an admin picks an OpenAI-compatible
// provider from and the catalogue page reads, and one provider's models.
import { answer } from './client';
import type { ModelCatalogueModelsResponse, ModelCatalogueResponse } from './types';

/** Every provider the catalogue lists, each with its OpenAI-compatible base URL where it has one. Admin only (403). */
export async function getCatalogue(): Promise<ModelCatalogueResponse> {
  return answer(await fetch('/api/catalogue'), 200, 'GET /api/catalogue');
}

/** The models of one provider, each field in force beside upstream's. Admin only (403); a 404 where the catalogue lists no such provider. */
export async function getCatalogueModels(provider: string): Promise<ModelCatalogueModelsResponse> {
  return answer(await fetch(`/api/catalogue/models?provider=${encodeURIComponent(provider)}`), 200, 'GET /api/catalogue/models');
}
