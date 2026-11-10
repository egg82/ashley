import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BenchPiece } from '../../../api/types.ts';
import { minutes, recipeCard } from './recipeCard.ts';

type Recipe = NonNullable<BenchPiece['recipe']>;

// The server's answer for a captured recipe page scaled from 4 to 6 (tests/test_bench_recipe_wire.py serves the same).
const SCALED: Recipe = {
  url: 'https://recipes.example/recipes/mash',
  name: 'Garlic Yukon Gold Mashed Potatoes',
  yield_text: '4 to 6 servings',
  makes: 4,
  serves: 6,
  factor: 1.5,
  prep_min: 15,
  cook_min: 25,
  total_min: 40,
  ingredients: [
    { text: '2 pounds Yukon gold potatoes', shown: '3 lb Yukon gold potatoes', amount: 2, amount_max: null, unit: 'pound', scaled: true },
    { text: 'Kosher salt', shown: 'Kosher salt', amount: null, amount_max: null, unit: null, scaled: false },
  ],
  steps: ['Boil the potatoes.', 'Mash.'],
};

test('a scaled recipe shows the server’s amounts and marks the line it could not scale', () => {
  const card = recipeCard(SCALED);
  assert.deepEqual(card.ingredients, [
    { text: '3 lb Yukon gold potatoes', asWritten: false },
    { text: 'Kosher salt', asWritten: true },
  ]);
  assert.equal(card.makes, 'For 6, scaled from 4 (the page says 4 to 6 servings)');
  assert.equal(card.times, 'Prep 15 min · Cook 25 min · Total 40 min');
  assert.equal(card.stepsNote, 'As the page wrote them, for 4');
  assert.equal(card.source?.hostname, 'recipes.example');
});

test('a recipe as written marks nothing and says so', () => {
  const card = recipeCard({ ...SCALED, serves: null, factor: null,
    ingredients: SCALED.ingredients.map((l) => ({ ...l, shown: l.text, scaled: false })) });
  assert.equal(card.makes, 'Makes 4 to 6 servings, as written');
  assert.ok(card.ingredients.every((l) => !l.asWritten));
  assert.equal(card.ingredients[0]?.text, '2 pounds Yukon gold potatoes');
  assert.equal(card.stepsNote, '');
});

test('a headcount with no count to scale from says it was not scaled', () => {
  const card = recipeCard({ ...SCALED, makes: null, factor: null, yield_text: '' });
  assert.equal(card.makes, 'For 6, not scaled: the page gives no count (not given)');
});

test('missing times are left out and a non-https address is not linked', () => {
  const card = recipeCard({ ...SCALED, prep_min: null, cook_min: null, total_min: 65, url: 'http://x.example/' });
  assert.equal(card.times, 'Total 1 h 5 min');
  assert.equal(card.source, null);
  assert.equal(minutes(120), '2 h');
  assert.equal(minutes(5), '5 min');
});
