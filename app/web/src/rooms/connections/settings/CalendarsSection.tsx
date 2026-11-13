// "On the hallway screen": one switch per calendar, on when the tablet shows its events today and tomorrow.
import type { House } from './house';
import { calendarLines } from './house';
import { idsOf, toggled, withIds } from './draft';
import { Row } from './Row';
import { draft, edit } from './state';
import { Switch } from './Switch';

const KEY = 'glance_calendars';

export function CalendarsSection({ house }: { house: House }) {
  const lines = calendarLines(house, idsOf(draft.value, KEY));
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>On the hallway screen</h2></div>
      <p class="cn-blurb">The calendars whose events the tablet shows for today and tomorrow, title and time. Anyone who stands in the hallway can read them, so pick only calendars the household shares. With none picked the tablet says the calendar is not connected.</p>
      {lines.length === 0
        ? <p class="set-empty">The house has no calendars.</p>
        : (
          <ul class="set-rows">
            {lines.map((l) => (
              <Row key={l.id} name={l.name} sub={l.sub} note={l.missing ? 'Not in Home Assistant right now' : null}>
                <Switch label="Show on the hallway screen" checked={l.only}
                  onChange={() => edit(withIds(draft.value, KEY, '', toggled(idsOf(draft.value, KEY), l.id)))} />
              </Row>
            ))}
          </ul>
        )}
    </section>
  );
}
