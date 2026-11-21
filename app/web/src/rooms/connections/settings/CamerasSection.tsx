// "Cameras she may look through": one switch per camera, on when she may list it and take a still from it when asked. Off for every
// camera until a person turns it on.
import type { House } from './house';
import { cameraLines } from './house';
import { idsOf, toggled, withIds } from './draft';
import { Row } from './Row';
import { draft, edit } from './state';
import { Switch } from './Switch';

const KEY = 'look_cameras';

export function CamerasSection({ house }: { house: House }) {
  const lines = cameraLines(house, idsOf(draft.value, KEY));
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>Cameras she may look through</h2></div>
      <p class="cn-blurb">A camera that is on here is one she can look through when someone asks: she takes one still, sees it and keeps it with the message. She never looks on her own, and a camera that is off is not even in her list. With none on she has no cameras.</p>
      {lines.length === 0
        ? <p class="set-empty">The house has no cameras.</p>
        : (
          <ul class="set-rows">
            {lines.map((l) => (
              <Row key={l.id} name={l.name} sub={l.sub} note={l.missing ? 'Not in Home Assistant right now' : null}>
                <Switch label="She may look through it" checked={l.only}
                  onChange={() => edit(withIds(draft.value, KEY, '', toggled(idsOf(draft.value, KEY), l.id)))} />
              </Row>
            ))}
          </ul>
        )}
    </section>
  );
}
