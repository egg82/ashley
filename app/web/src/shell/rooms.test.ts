import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isCataloguePath, roomForPath } from './rooms.ts';

test('the catalogue page is a path under the connections room, and only that path', () => {
  assert.equal(isCataloguePath('/connections/catalogue'), true);
  assert.equal(isCataloguePath('/connections/catalogue/'), true);
  assert.equal(roomForPath('/connections/catalogue').id, 'connections');
  for (const path of ['/connections', '/connections/catalogue/x', '/catalogue']) assert.equal(isCataloguePath(path), false, path);
});
