import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isCataloguePath, roomForPath, settingsOf } from './rooms.ts';

test('a connection\'s settings path names its connection', () => {
  assert.equal(settingsOf('/connections/12/settings'), 12);
  assert.equal(settingsOf('/connections/12/settings/'), 12);
});

test('no other path names a connection\'s settings', () => {
  for (const path of ['/connections', '/connections/12', '/connections/x/settings', '/workshop/12/settings', '/connections/12/settings/more']) {
    assert.equal(settingsOf(path), null, path);
  }
});

test('the settings page stays in the connections room', () => {
  assert.equal(roomForPath('/connections/12/settings').id, 'connections');
});

test('the catalogue page is a path under the connections room, and only that path', () => {
  assert.equal(isCataloguePath('/connections/catalogue'), true);
  assert.equal(isCataloguePath('/connections/catalogue/'), true);
  assert.equal(roomForPath('/connections/catalogue').id, 'connections');
  for (const path of ['/connections', '/connections/catalogue/x', '/catalogue']) assert.equal(isCataloguePath(path), false, path);
});
