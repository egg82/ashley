// What one screen shows of a camera: the feed it was given (`GET .../feed`, read again whenever the live feed says it
// changed), whether it is connecting, playing or has failed, and when it leaves on its own. The page's two screens, a
// person's and the kiosk's, each hold one (`screenCard`, `kioskCard`); `CameraFeed.tsx` shows it and opens the connection.
import { signal, type ReadonlySignal } from '@preact/signals';
import { kioskRoutes, screenRoutes, type FeedRoutes } from '../api/screenFeed';
import type { ScreenFeed } from '../api/types';
import { connect, type Link } from './connect';
import { screenToken } from '../session/screen';

/** `connecting` until the camera's picture plays, `live` while it does, `failed` when it could not be had or ended. */
export type Phase = 'connecting' | 'live' | 'failed';

export interface Showing {
  feed: ScreenFeed;
  phase: Phase;
}

export interface Card {
  /** What the screen shows, or null for no card. */
  showing: ReadonlySignal<Showing | null>;
  /** Asks what this screen should show now: after the live feed opened, may have missed something, or says it changed. */
  read(): Promise<void>;
  /** Opens the feed now shown in `video`, whose link ends it; the card hears whether it plays or fails. */
  open(video: HTMLVideoElement): Link;
  /** The picture is playing. */
  playing(): void;
  /** The feed could not be had, or ended before its time. */
  failed(): void;
  /** The person swiped or closed it: it goes now, and the server is told so it stays gone. */
  dismiss(): void;
}

export function createCard(routes: FeedRoutes, screen: string): Card {
  const showing = signal<Showing | null>(null);
  let leaves: ReturnType<typeof setTimeout> | undefined;

  function clear(): void {
    clearTimeout(leaves);
    showing.value = null;
  }

  function show(feed: ScreenFeed): void {
    clearTimeout(leaves);
    leaves = setTimeout(clear, feed.remaining_s * 1000);
    if (showing.value?.feed.camera_title !== feed.camera_title) showing.value = { feed, phase: 'connecting' };
  }

  const card: Card = {
    showing,
    async read() {
      try {
        const feed = await routes.read(screen);
        if (feed === null) clear();
        else show(feed);
      } catch {
        // unreachable now: what is shown stays, and the next change reads again
      }
    },
    open(video) {
      const feed = showing.value?.feed;
      if (!feed) return { close: () => undefined };
      return connect(routes, screen, feed, video, () => card.failed());
    },
    playing() {
      if (showing.value?.phase === 'connecting') showing.value = { ...showing.value, phase: 'live' };
    },
    failed() {
      if (showing.value) showing.value = { ...showing.value, phase: 'failed' };
    },
    dismiss() {
      clear();
      void routes.dismiss(screen).catch(() => undefined);
    },
  };
  return card;
}

export const screenCard: Card = createCard(screenRoutes, screenToken);
export const kioskCard: Card = createCard(kioskRoutes, screenToken);
