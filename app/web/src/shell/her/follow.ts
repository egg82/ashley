// Whether a page follows her when she moves it: never out from under the person. While they are in the middle of
// something (text typed into a field they are in, a drag, a piece being edited) the page waits for them to follow.

export interface PageState {
  /** The text of the field the person is in, or null when no text field has focus. */
  focusedText: string | null;
  /** Something is being carried: a piece by its grip, or a line to a room's bearing. */
  dragging: boolean;
  /** A piece of the bench shown has an edit open. */
  editing: boolean;
}

export type Follow = 'stay' | 'go' | 'wait';

/** What a page at `here` does when she moves it to `there`: nothing if it is there, else go, or wait while busy. */
export function follow(here: string, there: string, page: PageState): Follow {
  if (here === there) return 'stay';
  return busy(page) ? 'wait' : 'go';
}

/** Who made a bench's change, as Live says: she did, the person did on some screen, or no one did (a measurement). */
export type ChangedBy = 'her' | 'person' | null;

/** Whether a change to `bench` shows her mark away from the page: only her change, to a bench the page is not on
 * (`shownBench`, the bench the path names, if any). It never moves the page. */
export function workingAway(shownBench: number | null, bench: number, by: ChangedBy): boolean {
  return by === 'her' && shownBench !== bench;
}

/** Whether the offer `next` takes the place of the one waiting: a newer one does, except that her working somewhere
 * never displaces an offer to follow a move of the page, which is the stronger claim. */
export function replaces(waiting: 'moved' | 'working' | null, next: 'moved' | 'working'): boolean {
  return !(waiting === 'moved' && next === 'working');
}

export function busy(page: PageState): boolean {
  return !!page.focusedText?.trim() || page.dragging || page.editing;
}
