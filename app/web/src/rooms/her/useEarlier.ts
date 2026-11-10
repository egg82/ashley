// Reading earlier conversations in above a thread's open one, for any room that shows a thread: a page the person
// asked for keeps what they were looking at where it was; the first one, read when the thread is ready, leaves the
// newest at the foot.
import type { RefObject } from 'preact';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { EarlierStream } from './past';

export function useEarlier(stream: EarlierStream, thread: RefObject<HTMLDivElement>, open: number | null, ready: boolean) {
  const { earlier, earlierMore, earlierState, loadEarlier } = stream;
  const anchor = useRef<number | null>(null);
  const before = earlier.value.length;
  const reading = earlierState.value;
  const more = () => {
    anchor.current = thread.current?.scrollHeight ?? null;
    void loadEarlier(open);
  };
  useEffect(() => {
    if (ready && earlier.value.length === 0 && earlierState.value === 'idle') void loadEarlier(open);
  }, [ready]);
  useLayoutEffect(() => {
    const el = thread.current;
    if (!el || reading === 'loading') return;
    if (anchor.current === null) el.scrollTop = el.scrollHeight;
    else el.scrollTop += el.scrollHeight - anchor.current;
    anchor.current = null;
  }, [before, reading]);
  const nearTop = () => {
    const el = thread.current;
    if (el && el.scrollTop < 60 && ready && earlierMore.value && earlierState.value === 'idle') more();
  };
  return { before, reading, more, nearTop };
}
