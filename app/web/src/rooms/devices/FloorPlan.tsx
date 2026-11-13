// The household's devices drawn as a house: each in the room its place names, the house itself in a dashed band, and
// outside the wall the ones reached over the internet. On a phone the rooms stack into one column.
import type { ListedDevice } from '../../api/types';
import type { Plan, Room } from './plan';
import { Puck } from './Puck';

function Band({ cls, title, devices }: { cls: string; title: string; devices: ListedDevice[] }) {
  return (
    <section class={`fp-room ${cls}`} aria-label={title}>
      <header><span class="label">{title}</span><span class="meta">{devices.length}</span></header>
      {devices.map((d) => <Puck key={d.id} d={d} />)}
    </section>
  );
}

const Rooms = ({ rooms }: { rooms: Room[] }) => (
  <div class="fp-rooms">{rooms.map((r) => <Band key={r.key} cls="" title={r.name} devices={r.devices} />)}</div>
);

export function FloorPlan({ plan }: { plan: Plan }) {
  const inside = plan.rooms.length > 0 || plan.whole.length > 0;
  return (
    <div class="panel fp">
      {inside && (
        <div class="fp-wall">
          <span class="label fp-tag">The house</span>
          {plan.rooms.length > 0 && <Rooms rooms={plan.rooms} />}
          {plan.whole.length > 0 && <Band cls="whole" title="Whole house" devices={plan.whole} />}
        </div>
      )}
      {plan.online.length > 0 && <Band cls="online" title="Online · Discord" devices={plan.online} />}
      <ul class="fp-key meta">
        <li><span class="pk-mark dashed" aria-hidden="true"><i /></span>Whoever's there</li>
        <li><span class="pk-mark" aria-hidden="true"><i /><i /><i /></span>Shared</li>
        <li><span class="pk-mark" aria-hidden="true"><i /></span>One person's</li>
        <li>Rings: hears and speaks · Dots: shows text</li>
      </ul>
    </div>
  );
}
