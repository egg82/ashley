// What a cue says to a video piece's player. A provider's embed is driven by a `postMessage` to its iframe (YouTube's
// player takes `enablejsapi=1`, Vimeo's takes messages as it is); a direct file is a `<video>` element driven directly.
import type { LiveCue } from '../../../api/types';

export type Cue = Pick<LiveCue, 'action' | 'seconds'>;
export type Provider = 'youtube' | 'vimeo' | 'file';

/** The embed address with what the provider needs to accept commands. */
export function drivable(provider: Provider, embed: URL): URL {
  const url = new URL(embed.href);
  if (provider === 'youtube') url.searchParams.set('enablejsapi', '1');
  return url;
}

/** The message to post to a provider's iframe for `cue`, as the provider's player reads it; null for a seek without a
 *  time (the server refuses one, and a page does not trust what it is told). */
export function messageFor(provider: 'youtube' | 'vimeo', cue: Cue): string | null {
  if (cue.action === 'seek' && cue.seconds === null) return null;
  const to = cue.seconds ?? 0;
  if (provider === 'youtube') {
    const func = { play: 'playVideo', pause: 'pauseVideo', seek: 'seekTo' }[cue.action];
    return JSON.stringify({ event: 'command', func, args: cue.action === 'seek' ? [to, true] : [] });
  }
  if (cue.action === 'seek') return JSON.stringify({ method: 'setCurrentTime', value: to });
  return JSON.stringify({ method: cue.action });
}

/** Drives a `<video>` for `cue`. A play the browser refuses (nobody has touched the page yet) is left unplayed. */
export function driveFile(video: Pick<HTMLVideoElement, 'play' | 'pause' | 'currentTime'>, cue: Cue): void {
  if (cue.action === 'pause') video.pause();
  else if (cue.action === 'seek') {
    if (cue.seconds !== null) video.currentTime = cue.seconds;
  } else void Promise.resolve(video.play()).catch(() => undefined);
}
