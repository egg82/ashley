// A camera's live feed on a screen: what this screen shows, its swipe, and the signalling of its WebRTC offer, for the
// person's page (`/api/screens/feed`) and the paired kiosk (`/api/kiosk/feed`). The media goes from the camera to the page;
// these routes carry only the offer, the camera's answer and candidates, and the screen's token (`session/screen.ts`).
import { ApiError } from './client';
import type { FeedSignal, ScreenFeed } from './types';

export interface FeedRoutes {
  /** The feed this screen shows, or null. 401 and 503 throw ApiError. */
  read(screen: string): Promise<ScreenFeed | null>;
  /** Takes the feed off this screen. */
  dismiss(screen: string): Promise<void>;
  /** Relays the offer; resolves with the stream of the camera's signals, which ends when `abort` fires or the server
   * ends it. Throws ApiError for a refusal. */
  offer(screen: string, sdp: string, abort: AbortSignal): Promise<ReadableStream<Uint8Array>>;
  /** Relays one of this page's ICE candidates for the session. */
  candidate(screen: string, session: string, init: RTCIceCandidateInit): Promise<void>;
}

async function send(path: string, method: string, body: object | undefined, abort?: AbortSignal): Promise<Response> {
  return fetch(path, { method, signal: abort, ...(body ? { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {}) });
}

export function routes(prefix: '/api/screens/feed' | '/api/kiosk/feed'): FeedRoutes {
  return {
    async read(screen) {
      const response = await send(`${prefix}?screen=${screen}`, 'GET', undefined);
      if (response.status !== 200) throw new ApiError(response.status, `GET ${prefix}`);
      return ((await response.json()) as { feed: ScreenFeed | null }).feed;
    },
    async dismiss(screen) {
      const response = await send(`${prefix}?screen=${screen}`, 'DELETE', undefined);
      if (response.status !== 204) throw new ApiError(response.status, `DELETE ${prefix}`);
    },
    async offer(screen, sdp, abort) {
      const response = await send(`${prefix}/offer`, 'POST', { screen, offer: sdp }, abort);
      if (response.status !== 200 || response.body === null) throw new ApiError(response.status, `POST ${prefix}/offer`);
      return response.body;
    },
    async candidate(screen, session, init) {
      const response = await send(`${prefix}/candidate`, 'POST', {
        screen, session_id: session, candidate: init.candidate, sdp_mid: init.sdpMid ?? null,
        sdp_m_line_index: init.sdpMLineIndex ?? null, username_fragment: init.usernameFragment ?? null });
      if (response.status !== 204) throw new ApiError(response.status, `POST ${prefix}/candidate`);
    },
  };
}

/** The person's page's routes. */
export const screenRoutes: FeedRoutes = routes('/api/screens/feed');
/** The paired kiosk's routes. */
export const kioskRoutes: FeedRoutes = routes('/api/kiosk/feed');

/** The signals in a stream of `data:` lines, as they arrive; comment lines are skipped. */
export async function* signals(stream: ReadableStream<Uint8Array>): AsyncGenerator<FeedSignal> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let rest = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      rest += decoder.decode(value, { stream: true });
      let end = rest.indexOf('\n');
      while (end >= 0) {
        const line = rest.slice(0, end).trimEnd();
        rest = rest.slice(end + 1);
        if (line.startsWith('data: ')) yield JSON.parse(line.slice(6)) as FeedSignal;
        end = rest.indexOf('\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}
