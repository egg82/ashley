// What the look page waits for before it says it is ready: every model view that was asked for and has either drawn
// its frame or given up. A view registers its whole load-and-draw with `tracked`.
const pending = new Set<Promise<unknown>>();

export function tracked<T>(work: Promise<T>): Promise<T> {
  pending.add(work);
  const done = () => { pending.delete(work); };
  work.then(done, done);
  return work;
}

/** Resolves once nothing registered is still drawing, including a view registered while it waited. */
export async function allDrawn(): Promise<void> {
  while (pending.size) await Promise.allSettled([...pending]);
}
