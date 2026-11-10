// The camera: the field's transform centres the room it points at and zooms to that room's scale. A change of room
// eases there (the CSS transition); a landing or a resize jumps.
import { useLayoutEffect, useRef } from 'preact/hooks';
import { camera, jump } from '../flight';
import { room, type RoomId } from '../rooms';
import { Field } from './Field';

function transformFor(id: RoomId): string {
  const { at, z } = room(id);
  return `translate(${innerWidth / 2 - at[0] * z}px, ${innerHeight / 2 - at[1] * z}px) scale(${z})`;
}

function setCamera(el: HTMLElement, id: RoomId, instant: boolean): void {
  if (instant) el.style.transition = 'none';
  el.style.transform = transformFor(id);
  if (instant) {
    void el.offsetWidth;
    el.style.transition = '';
  }
}

export function World() {
  const ref = useRef<HTMLDivElement>(null);
  const seenJump = useRef(-1);
  const id = camera.value;
  const jumps = jump.value;

  useLayoutEffect(() => {
    if (!ref.current) return;
    setCamera(ref.current, id, jumps !== seenJump.current);
    seenJump.current = jumps;
  }, [id, jumps]);

  useLayoutEffect(() => {
    const onResize = () => ref.current && setCamera(ref.current, camera.peek(), true);
    addEventListener('resize', onResize);
    return () => removeEventListener('resize', onResize);
  }, []);

  return (
    <div id="field">
      <div id="world" ref={ref}>
        <Field />
      </div>
    </div>
  );
}
