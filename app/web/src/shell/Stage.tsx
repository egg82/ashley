// The rooms over the field: the one shown, plus the one leaving during a flight. A room entered is laid out, her mark
// is sent to its dock while it still sits in place, and only then does it arrive along the travel vector.
import type { ComponentType } from 'preact';
import { useLayoutEffect, useRef } from 'preact/hooks';
import { ConnectionsRoom } from '../rooms/connections/ConnectionsRoom';
import { DevicesRoom } from '../rooms/devices/DevicesRoom';
import { HerRoom } from '../rooms/her/HerRoom';
import { MemoryRoom } from '../rooms/memory/MemoryRoom';
import { SpendRoom } from '../rooms/spend/SpendRoom';
import { WorkshopRoom } from '../rooms/workshop/WorkshopRoom';
import { SigninRoom } from '../signin/SigninRoom';
import { arrive, arriving, entering, leaving, shown, vector, wasFlown } from './flight';
import { dockIn } from './her/dock';
import type { RoomId } from './rooms';

const VIEWS: Record<RoomId, { view: ComponentType; label: string }> = {
  signin: { view: SigninRoom, label: 'Sign in' },
  her: { view: HerRoom, label: 'Ashley' },
  memory: { view: MemoryRoom, label: 'Memory' },
  workshop: { view: WorkshopRoom, label: 'Workshop' },
  devices: { view: DevicesRoom, label: 'Devices' },
  connections: { view: ConnectionsRoom, label: 'Connections' },
  spend: { view: SpendRoom, label: 'Usage' },
};

function phase(id: RoomId): string {
  if (id === leaving.value) return 'leaving';
  return arriving.value ? 'on arriving' : 'on';
}

export function Stage() {
  const on = useRef<HTMLElement>(null);
  const current = shown.value;
  const out = leaving.value;
  const [vx, vy] = vector.value;

  useLayoutEffect(() => {
    if (!entering.value) return;
    dockIn(on.current, !wasFlown());
    arrive();
  }, [current, entering.value]);

  const rooms = out && out !== current ? [out, current] : [current];
  return (
    <div class="stage" style={{ '--vx': `${vx}px`, '--vy': `${vy}px` }}>
      {rooms.map((id) => {
        const { view: View, label } = VIEWS[id];
        return (
          <section key={id} ref={id === current ? on : undefined} class={`room ${phase(id)}`} data-room={id} aria-label={label}>
            <View />
          </section>
        );
      })}
    </div>
  );
}
