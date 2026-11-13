import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { ListedDevice } from '../../api/types';
import { inPlace, itDoes, sentenceOf } from './sentence.ts';

const dev = (patch: Partial<ListedDevice>): ListedDevice =>
  ({ id: 1, name: 'Hall tablet', place: 'hallway', form: 'other', audience: 'present', medium: 'text', takes_controls: false, ...patch });
const read = (d: ListedDevice): string => { const s = sentenceOf(d); return s.name + s.before + s.who + s.after; };

test('a screen that takes controls says it can be tapped, by what the server says and not by its medium', () => {
  assert.equal(read(dev({ takes_controls: true })), 'Hall tablet, a screen whoever is there can read and tap.');
  assert.equal(read(dev({})), 'Hall tablet, a device that reads and writes with whoever is there.');
});

test('each form reads as what it is wired to', () => {
  assert.equal(read(dev({ name: 'echo', form: 'satellite', medium: 'spoken' })), 'echo, a voice satellite that hears and answers whoever is there.');
  assert.equal(read(dev({ name: 'srv', form: 'discord_server', audience: 'household' })), 'srv, a Discord server she reads and writes in with all of you.');
  assert.match(read(dev({ name: 'HA', form: 'house', audience: 'household' })), /^HA, your house itself\..* all of you\.$/);
});

test('a device only its owner uses says so, and a spoken one hears', () => {
  assert.equal(read(dev({ audience: 'owner', medium: 'spoken' })), 'Hall tablet, a device that hears and answers its owner alone.');
  assert.equal(itDoes(dev({ medium: 'spoken' })), 'Hears and speaks');
  assert.equal(itDoes(dev({})), 'Shows text');
});

test('a place reads as a heading', () => {
  assert.equal(inPlace(' living room '), 'In the living room');
});
