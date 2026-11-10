import type { Cue } from '../pieces/player';

/** A time in a recording as a person reads it: `m:ss`, or `h:mm:ss` from an hour on. */
export function clockText(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

/** What a cue did, in words. */
export function cueText(cue: Cue): string {
  if (cue.action === 'seek') return `Ashley moved to ${clockText(cue.seconds ?? 0)}`;
  return cue.action === 'play' ? 'Ashley pressed play' : 'Ashley paused it';
}
