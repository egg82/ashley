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

export function busy(page: PageState): boolean {
  return !!page.focusedText?.trim() || page.dragging || page.editing;
}
