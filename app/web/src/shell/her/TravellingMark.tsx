// Her one body on screen. Rooms lay out empty docks; this element is drawn over whichever one she is in.
import { useLayoutEffect, useRef } from 'preact/hooks';
import { AshleyMark } from '../../components/AshleyMark';
import { redock, setBody } from './dock';
import { herState } from './state';

export function TravellingMark() {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    setBody(ref.current);
    const snap = () => redock(true);
    // A room's content changed (a button, the loading lines): her dock may have moved, so she follows it.
    const moved = new MutationObserver(() => redock(false));
    moved.observe(document.getElementById('app')!, { childList: true, subtree: true });
    void document.fonts.ready.then(snap);
    // Capture: a docked mark rides any scroll box its dock is in.
    addEventListener('scroll', snap, true);
    addEventListener('resize', snap);
    return () => {
      setBody(null);
      moved.disconnect();
      removeEventListener('scroll', snap, true);
      removeEventListener('resize', snap);
    };
  }, []);

  const state = herState.value;
  return (
    // No `class` here: dock.ts owns it (`snap`), so a re-render mid-spring cannot cut the spring short.
    <div id="her" ref={ref} data-state={state}>
      <AshleyMark state={state} />
    </div>
  );
}
