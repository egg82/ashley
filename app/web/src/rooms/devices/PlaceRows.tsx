// The same devices in words, a heading per place and a sentence per device; each row selects its device.
import type { ListedDevice } from '../../api/types';
import { select, selected } from './devices';
import type { Plan } from './plan';
import { inPlace, sentenceOf } from './sentence';

function Row({ d }: { d: ListedDevice }) {
  const s = sentenceOf(d);
  return (
    <li>
      <button class="pr-row" type="button" aria-pressed={selected.value === d.id} onClick={() => select(d.id)}>
        <b>{s.name}</b>{s.before}<span class="pr-who">{s.who}</span>{s.after}
      </button>
    </li>
  );
}

function Place({ title, devices }: { title: string; devices: ListedDevice[] }) {
  return (
    <section class="pr-place">
      <h3>{title}</h3>
      <ul>{devices.map((d) => <Row key={d.id} d={d} />)}</ul>
    </section>
  );
}

export function PlaceRows({ plan }: { plan: Plan }) {
  return (
    <div class="panel pr">
      {plan.rooms.map((r) => <Place key={r.key} title={inPlace(r.name)} devices={r.devices} />)}
      {plan.whole.length > 0 && <Place title="Across the house" devices={plan.whole} />}
      {plan.online.length > 0 && <Place title="On Discord" devices={plan.online} />}
    </div>
  );
}
