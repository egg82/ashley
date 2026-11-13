// What she announces to this screen over its live feed (`LiveAnnounce`: on the kiosk when someone is home, on a person's
// page while they are away): her voice played from the clip and its line shown while it plays, then for a few seconds
// more. Only a page in the foreground takes one; a newer announcement replaces the one showing. A play the browser
// refuses shows a play control instead, as her spoken replies do (`voice.ts`).
import { signal, type ReadonlySignal } from '@preact/signals';
import { clipVoiceUrl, getClipLine } from '../api/client';

/** `playing`: her voice is playing or about to; `blocked`: the browser refused to start it, so a control plays it on a
 * tap; `said`: it finished, and the line stays until `LINGER_MS` has passed. */
export interface Announcement {
  clip: string;
  line: string;
  phase: 'playing' | 'blocked' | 'said';
}

export const LINGER_MS = 8000;

const current = signal<Announcement | null>(null);
export const announcement: ReadonlySignal<Announcement | null> = current;
let audio: HTMLAudioElement | null = null;
let linger: ReturnType<typeof setTimeout> | undefined;

function showing(clip: string): boolean {
  return current.value?.clip === clip;
}

function said(clip: string): void {
  if (!showing(clip)) return;
  current.value = { ...current.value!, phase: 'said' };
  linger = setTimeout(() => {
    if (showing(clip)) current.value = null;
  }, LINGER_MS);
}

function play(clip: string): void {
  audio ??= new Audio();
  const element = audio;
  element.onended = element.onerror = () => said(clip);
  element.src = clipVoiceUrl(clip);
  void element.play()?.catch((error: unknown) => {
    if (!showing(clip)) return;
    if (error instanceof DOMException && error.name === 'NotAllowedError') current.value = { ...current.value!, phase: 'blocked' };
    else said(clip);
  });
}

/** The feed named clip `clip`: shows its line and plays it, when the page is in the foreground and the line can be
 * read; otherwise nothing, since an announcement is for whoever is looking now. */
export async function announced(clip: string): Promise<void> {
  if (document.visibilityState !== 'visible') return;
  let line: string;
  try {
    line = (await getClipLine(clip)).line;
  } catch {
    return;
  }
  current.value = { clip, line, phase: 'playing' };
  play(clip);
}

/** Plays the announcement whose play the browser refused, from a tap on its control. */
export function playAnnouncement(): void {
  const shown = current.value;
  if (shown?.phase !== 'blocked') return;
  current.value = { ...shown, phase: 'playing' };
  play(shown.clip);
}

/** Stops her voice and takes the line away, from a tap on its control. */
export function dismiss(): void {
  clearTimeout(linger);
  current.value = null;
  if (audio === null) return;
  audio.onended = audio.onerror = null;
  audio.pause();
}
