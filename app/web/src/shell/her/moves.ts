// She moved the person's page (the live feed's `page` event): this page flies there with the shell's own flight, or,
// while the person is in the middle of something (`follow.ts`), her mark waits at the destination's bearing and the
// page offers to follow. The one owner of `waiting`; each open tab decides by its own state.
import { signal } from '@preact/signals';
import { carried } from '../../rooms/workshop/pieces/drag';
import { draftsOn } from '../../rooms/workshop/model/drafts';
import { carryTo } from '../carry';
import { benchOf, pathTo, type NavRoomId } from '../rooms';
import { getBenches } from '../../api/client';
import { follow, replaces, workingAway, type ChangedBy, type PageState } from './follow';

export interface Waiting {
  room: NavRoomId;
  path: string;
  /** She moved the page and it stayed (`moved`), or she is working at a bench the page is not on (`working`). */
  kind: 'moved' | 'working';
  /** The bench's title, once known, for `working`. */
  title: string | null;
}

/** Where she went, or is working, while this page stayed, until the person follows, stays or goes somewhere themselves
 * (`pageMoved`). A newer change replaces it (`replaces`). */
export const waiting = signal<Waiting | null>(null);

function here(): string {
  return location.pathname.replace(/\/+$/, '') || '/';
}

function textOf(el: Element | null): string | null {
  if (el instanceof HTMLTextAreaElement) return el.value;
  if (el instanceof HTMLInputElement) return ['text', 'search', 'url', 'email'].includes(el.type) ? el.value : null;
  if (el instanceof HTMLElement && el.isContentEditable) return el.textContent;
  return null;
}

function pageNow(): PageState {
  const bench = benchOf(here());
  return {
    focusedText: textOf(document.activeElement),
    dragging: carried.value !== null || carryTo.value !== null,
    editing: bench !== null && draftsOn(bench).length > 0,
  };
}

function go(path: string): void {
  history.pushState(null, '', path);
  // The router reads the address on popstate, as it does for back and forward, and the shell flies there.
  dispatchEvent(new PopStateEvent('popstate'));
}

/** The live feed says she moved this person's page to `room` (a bench in the workshop when `bench` is set). */
export function herMoved(room: NavRoomId, bench: number | null): void {
  const path = pathTo(room, bench);
  const now = follow(here(), path, pageNow());
  if (now === 'wait') waiting.value = { room, path, kind: 'moved', title: null };
  else if (replaces(waiting.value?.kind ?? null, 'moved')) waiting.value = null;
  if (now === 'go') go(path);
}

/** The live feed says command `by` changed bench `bench`: when the page is not on it and she made it, her mark shows she
 * is working there, named by the bench's title. The page itself stays where it is. */
export function benchChangedBy(bench: number, by: ChangedBy): void {
  if (!workingAway(benchOf(here()), bench, by) || !replaces(waiting.value?.kind ?? null, 'working')) return;
  const offer: Waiting = { room: 'workshop', path: pathTo('workshop', bench), kind: 'working', title: null };
  waiting.value = offer;
  void getBenches().then((open) => {
    const title = open.benches.find((b) => b.id === bench)?.title;
    if (title && waiting.value === offer) waiting.value = { ...offer, title };
  }, () => undefined);
}

/** The person taps to follow her. */
export function followHer(): void {
  const to = waiting.value;
  waiting.value = null;
  if (to) go(to.path);
}

/** The person stays where they are; her mark comes back. */
export function stayHere(): void {
  waiting.value = null;
}

/** The page's path changed: wherever the person went, they are no longer waiting to follow her. */
export function pageMoved(): void {
  waiting.value = null;
}
