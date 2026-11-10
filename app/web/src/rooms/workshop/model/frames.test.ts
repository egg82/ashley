import assert from 'node:assert/strict';
import { test } from 'node:test';
import { framedBody, isFramed, parseStart } from './frames.ts';

test('a site is its address alone, trimmed', () => {
  assert.equal(framedBody('site', '  https://en.wikipedia.org/wiki/Graph_theory ', 0), 'https://en.wikipedia.org/wiki/Graph_theory');
});

test('a video is a JSON object of its address, with a start only when there is one', () => {
  assert.deepEqual(JSON.parse(framedBody('video', ' https://youtu.be/dQw4w9WgXcQ ', 0)), { url: 'https://youtu.be/dQw4w9WgXcQ' });
  assert.deepEqual(JSON.parse(framedBody('video', 'https://youtu.be/dQw4w9WgXcQ', 90)), { url: 'https://youtu.be/dQw4w9WgXcQ', start: 90 });
});

test('a start is seconds, minutes:seconds or hours:minutes:seconds; empty is the beginning; anything else is null', () => {
  assert.equal(parseStart(''), 0);
  assert.equal(parseStart(' 90 '), 90);
  assert.equal(parseStart('1:30'), 90);
  assert.equal(parseStart('1:02:03'), 3723);
  for (const bad of ['-1', '1.5', 'a', '1:60', '1:', ':30', '1:2:3:4', '1e3']) assert.equal(parseStart(bad), null, bad);
});

test('only the site and video formats are framed', () => {
  assert.equal(isFramed('site'), true);
  assert.equal(isFramed('video'), true);
  assert.equal(isFramed('markdown'), false);
});
