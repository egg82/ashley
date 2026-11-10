/** The line of a transcript being spoken at `seconds`: the one with the latest start at or before it, the later line
 *  when two start together. -1 before the first line starts, or for no lines. */
export function lineAt(starts: readonly number[], seconds: number): number {
  let found = -1;
  let latest = -Infinity;
  starts.forEach((start, i) => {
    if (start <= seconds && start >= latest) {
      found = i;
      latest = start;
    }
  });
  return found;
}
