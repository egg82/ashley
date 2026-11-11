import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { PersonaSection } from '../../api/types';
import { differs, inForce } from './personaText.ts';

const shipped: PersonaSection = { section: 'wit', label: 'Her wit', shipped: 'Shipped.', override: null, persona_version: 0, history: [] };
const own: PersonaSection = { ...shipped, override: 'Ours.', persona_version: 2 };

test('she uses the household text when it has one, else the shipped', () => {
  assert.equal(inForce(shipped), 'Shipped.');
  assert.equal(inForce(own), 'Ours.');
});

test('a draft differs only when its text, trimmed, is new and not empty', () => {
  assert.equal(differs(shipped, ' Shipped. \n'), false);
  assert.equal(differs(shipped, '   '), false);
  assert.equal(differs(shipped, 'Ours.'), true);
  assert.equal(differs(own, 'Ours.'), false);
  assert.equal(differs(own, 'Shipped.'), true);
});
