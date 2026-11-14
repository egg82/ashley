import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ModelCatalogueProvider } from '../../api/types';
import { pick, pickable, type Pickable } from './providerChoice.ts';

const PATTERN = '[a-z0-9][a-z0-9_-]{0,39}';

function listed(provider: string, name: string, api: string | null): ModelCatalogueProvider {
  return { provider, name, api, model_count: 3, overridden_count: 0, has_connection: null };
}

const providers = [
  listed('openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1'),
  listed('anthropic', 'Anthropic', null),
  listed('groq', 'Groq', 'https://api.groq.com/openai/v1'),
  listed('Odd.Id', 'Odd', 'https://odd.test/v1'),
];
const from = pickable(providers);
const empty = { provider: null, address: '', label: '' };

function offered(id: string): Pickable {
  const found = from.find((p) => p.provider === id);
  assert.ok(found, id);
  return found;
}
const groq = offered('groq');
const odd = offered('Odd.Id');
const openrouter = offered('openrouter');

test('only providers with a base URL are offered, by name', () => {
  assert.deepEqual(from.map((p) => p.provider), ['groq', 'Odd.Id', 'openrouter']);
});

test('picking a provider prefills its base URL and its id as the name', () => {
  assert.deepEqual(pick(empty, groq, from, PATTERN), { provider: 'groq', address: 'https://api.groq.com/openai/v1', label: 'groq' });
});

test('a name the person typed survives picking another provider', () => {
  const typed = { provider: 'groq', address: 'https://api.groq.com/openai/v1', label: 'fast' };
  assert.deepEqual(pick(typed, openrouter, from, PATTERN), { provider: 'openrouter', address: 'https://openrouter.ai/api/v1', label: 'fast' });
});

test('a prefilled name follows the next pick, and an id that is not a route name prefills none', () => {
  const picked = pick(empty, groq, from, PATTERN);
  assert.equal(pick(picked, openrouter, from, PATTERN).label, 'openrouter');
  assert.equal(pick(picked, odd, from, PATTERN).label, '');
});

test('back to a custom address clears what the pick filled and keeps what the person typed', () => {
  const picked = pick(empty, groq, from, PATTERN);
  assert.deepEqual(pick(picked, null, from, PATTERN), empty);
  const edited = { ...picked, address: 'https://eu.groq.test/v1', label: 'mine' };
  assert.deepEqual(pick(edited, null, from, PATTERN), { provider: null, address: 'https://eu.groq.test/v1', label: 'mine' });
});
