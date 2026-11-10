// The workshop, at bearing 180: the benches she and the person make things on. `/workshop` is the benches, and
// `/workshop/<id>` one bench; moving between them stays in the room, the bench growing out of its card.
import { useLocation } from 'preact-iso';
import { useLayoutEffect, useRef } from 'preact/hooks';
import { redock } from '../../shell/her/dock';
import { benchOf } from '../../shell/rooms';
import { BenchView } from './bench/BenchView';
import { BenchList } from './list/BenchList';

export function WorkshopRoom() {
  const { path } = useLocation();
  const id = benchOf(path);
  // The shell docks her when the room is entered; moving between the benches and a bench inside it docks her again.
  const entered = useRef(false);
  useLayoutEffect(() => {
    if (entered.current) redock(false);
    entered.current = true;
  }, [id]);
  return <div class="ws" key={id ?? 'list'}>{id === null ? <BenchList /> : <BenchView id={id} />}</div>;
}
