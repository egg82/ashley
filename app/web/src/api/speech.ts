// Her voice and the person's: the transcript routes and their limits, and where her spoken replies and announced clips
// are read from.
import { answer } from './client';
import type { ClipLine, SpokenLimits, Transcript } from './types';

/** The longest utterance the transcript routes take. */
export async function getSpokenLimits(): Promise<SpokenLimits> {
  return answer(await fetch('/api/spoken/limits'), 200, 'GET /api/spoken/limits');
}

/** What was heard in one utterance (a 16 kHz mono WAV) sent to `route`; empty when nothing was said. */
async function transcribe(route: '/api/chat/transcripts' | '/api/kiosk/transcripts', audio: Blob): Promise<Transcript> {
  const response = await fetch(route, { method: 'POST', headers: { 'content-type': 'audio/wav' }, body: audio });
  return answer(response, 200, `POST ${route}`);
}

/** What the signed-in person said in `audio`. */
export async function transcribeChat(audio: Blob): Promise<Transcript> {
  return transcribe('/api/chat/transcripts', audio);
}

/** What was said at the kiosk in `audio`. */
export async function transcribeKiosk(audio: Blob): Promise<Transcript> {
  return transcribe('/api/kiosk/transcripts', audio);
}

/** Where her voice for turn `id` is read, for the person's own thread. A same-origin GET, so the session cookie rides it. */
export function chatVoiceUrl(id: number): string {
  return `/api/chat/turns/${id}/voice`;
}

/** Where her voice for turn `id` is read, for the kiosk's thread. */
export function kioskVoiceUrl(id: number): string {
  return `/api/kiosk/turns/${id}/voice`;
}

/** Where her voice for an announced clip is read; the token is its only credential. */
export function clipVoiceUrl(clip: string): string {
  return `/api/voice/clips/${encodeURIComponent(clip)}`;
}

/** The line shown beside an announced clip's voice. */
export async function getClipLine(clip: string): Promise<ClipLine> {
  return answer(await fetch(`/api/voice/clips/${encodeURIComponent(clip)}/line`), 200, 'GET /api/voice/clips/{token}/line');
}
