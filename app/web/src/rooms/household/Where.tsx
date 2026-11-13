// Beside the sentence: the household's time zone as a dial, and the house on a globe.
import { household } from '../../household/household';
import { HouseMap } from './HouseMap';
import { TimeDial } from './TimeDial';

export function Where() {
  if (!household.value) return null;
  return (
    <div class="panel">
      <div class="ph"><h3>Where and when</h3></div>
      <div class="dc-body hh-where">
        <TimeDial />
        <HouseMap />
      </div>
    </div>
  );
}
