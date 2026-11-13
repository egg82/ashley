// Picking an OpenAI-compatible provider: one the model catalogue lists with a base URL, which prefills the address (and
// the name, while the person has not typed one), or a custom address, whose calls are unpriced.
import type { ModelCatalogueProvider } from '../../api/types';

/** A catalogue provider that can be picked: its id, its name, and the base URL its `api` gives. */
export interface Pickable {
  provider: string;
  name: string;
  api: string;
}

/** What the form holds: the catalogue provider picked (null: a custom address), the address and the name. */
export interface Picked {
  provider: string | null;
  address: string;
  label: string;
}

/** The providers that list a base URL, by name. */
export function pickable(providers: ModelCatalogueProvider[]): Pickable[] {
  return providers
    .flatMap((p) => (p.api ? [{ provider: p.provider, name: p.name, api: p.api }] : []))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** The name a provider's id makes, when it fits `pattern`; empty otherwise. */
function nameFor(provider: string, pattern: string | null | undefined): string {
  const name = provider.toLowerCase();
  return pattern && !new RegExp(`^(?:${pattern})$`).test(name) ? '' : name;
}

/** The form after `choice` is picked (null: a custom address). A provider's base URL replaces the address; its id
 * becomes the name unless the person typed their own. Back to custom, an address the last pick filled is cleared. */
export function pick(now: Picked, choice: Pickable | null, from: Pickable[], pattern?: string | null): Picked {
  const previous = from.find((p) => p.provider === now.provider) ?? null;
  const filledName = previous ? nameFor(previous.provider, pattern) : '';
  const ownName = now.label !== '' && now.label !== filledName;
  if (choice === null) {
    return { provider: null, address: previous && now.address === previous.api ? '' : now.address, label: ownName ? now.label : '' };
  }
  return { provider: choice.provider, address: choice.api, label: ownName ? now.label : nameFor(choice.provider, pattern) };
}
