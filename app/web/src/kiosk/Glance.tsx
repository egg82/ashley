// The glance of the fixed page: the time and date on this screen's clock, who is home, and the sources with nothing
// behind them yet. "Not connected" where no source exists.
import { Fragment } from 'preact';
import { Clock } from './Clock';
import { HomeNames } from './Home';
import { glance } from './state';

const SOURCE = { calendar: 'Calendar', reminders: 'Reminders' };

export function Glance() {
  const seen = glance.value;
  return (
    <div class="k-glance">
      <Clock />
      <dl class="k-facts">
        <dt class="label">Home</dt>
        <dd><HomeNames names={seen?.home} /></dd>
        {(seen?.not_connected ?? ['calendar', 'reminders']).map((s) => (
          <Fragment key={s}>
            <dt class="label">{SOURCE[s]}</dt>
            <dd><span class="unk">not connected</span></dd>
          </Fragment>
        ))}
      </dl>
    </div>
  );
}
