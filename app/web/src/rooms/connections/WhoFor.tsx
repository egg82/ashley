// One address with its two-way switch: who may ask her about it. The pressed side is the state, so no chip and no
// opposite-action button say it twice.
import { useId } from 'preact/hooks';
import type { ConnectionResource, HouseholdConnection } from '../../api/types';
import { share } from './connections';
import { sharedFor, whoOf, WHO, type Who } from './who';

const SIDES: readonly Who[] = ['me', 'household'];

export function WhoFor({ c, r }: { c: HouseholdConnection; r: ConnectionResource }) {
  const group = useId();
  const now = whoOf(r.shared);
  return (
    <div class="cn-addr">
      <span class="cn-addr-name">{r.name}</span>
      <fieldset class="cn-who">
        <legend>{`Who can ask about ${r.name}`}</legend>
        {SIDES.map((side) => (
          <label key={side} class={side}>
            <input type="radio" name={group} checked={now === side}
              onChange={() => { const to = sharedFor(r.shared, side); if (to !== null) void share(c, r.ref, to); }} />
            {WHO[side]}
          </label>
        ))}
      </fieldset>
    </div>
  );
}
