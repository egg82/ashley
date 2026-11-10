import assert from 'node:assert/strict';
import { test } from 'node:test';
import { showsCard } from './siteCard.ts';

test('a site the server measured as refusing a frame is a link card', () => {
  assert.equal(showsCard({ frameable: false, title: 'A model' }), true);
  assert.equal(showsCard({ frameable: false, title: '' }), true);
});

test('a site that frames, or one not measured, is framed as before', () => {
  assert.equal(showsCard({ frameable: true, title: 'A model' }), false);
  assert.equal(showsCard({ frameable: null, title: '' }), false);
  assert.equal(showsCard(null), false);
});
