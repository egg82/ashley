import assert from 'node:assert/strict';
import { test } from 'node:test';
import { drivable, driveFile, messageFor } from './player.ts';

test("YouTube's player is told in its command messages, a seek with the time and allowing a seek ahead", () => {
  assert.deepEqual(JSON.parse(messageFor('youtube', { action: 'play', seconds: null }) ?? ''), { event: 'command', func: 'playVideo', args: [] });
  assert.deepEqual(JSON.parse(messageFor('youtube', { action: 'pause', seconds: null }) ?? ''), { event: 'command', func: 'pauseVideo', args: [] });
  assert.deepEqual(JSON.parse(messageFor('youtube', { action: 'seek', seconds: 90.5 }) ?? ''), { event: 'command', func: 'seekTo', args: [90.5, true] });
});

test("Vimeo's player is told in its method messages", () => {
  assert.deepEqual(JSON.parse(messageFor('vimeo', { action: 'play', seconds: null }) ?? ''), { method: 'play' });
  assert.deepEqual(JSON.parse(messageFor('vimeo', { action: 'pause', seconds: null }) ?? ''), { method: 'pause' });
  assert.deepEqual(JSON.parse(messageFor('vimeo', { action: 'seek', seconds: 12 }) ?? ''), { method: 'setCurrentTime', value: 12 });
});

test('a seek without a time says nothing', () => {
  assert.equal(messageFor('youtube', { action: 'seek', seconds: null }), null);
  assert.equal(messageFor('vimeo', { action: 'seek', seconds: null }), null);
});

test("only YouTube's embed address is changed, to take commands", () => {
  const youtube = drivable('youtube', new URL('https://www.youtube-nocookie.com/embed/abc?start=5'));
  assert.equal(youtube.searchParams.get('enablejsapi'), '1');
  assert.equal(youtube.searchParams.get('start'), '5');
  const vimeo = new URL('https://player.vimeo.com/video/1#t=5s');
  assert.equal(drivable('vimeo', vimeo).href, vimeo.href);
});

test('a file is played, paused and sought directly; a refused play is not an error', async () => {
  const calls: string[] = [];
  const video = { currentTime: 0, play: () => { calls.push('play'); return Promise.reject(new Error('NotAllowedError')); }, pause: () => { calls.push('pause'); } };
  driveFile(video, { action: 'play', seconds: null });
  driveFile(video, { action: 'pause', seconds: null });
  driveFile(video, { action: 'seek', seconds: 30 });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(calls, ['play', 'pause']);
  assert.equal(video.currentTime, 30);
});
