// "Cameras she may look through": one switch per camera, on when she may list it and take a still from it when asked. Off for every
// camera until a person turns it on. Home Assistant's, Bambuddy's and a herdr bridge's connections all carry the setting; the kind says which
// domain of its catalogue holds the cameras.
import type { House } from './house';
import { cameraLines } from './house';
import { idsOf, toggled, withIds } from './draft';
import { Row } from './Row';
import { draft, edit, settings } from './state';
import { Switch } from './Switch';

const KEY = 'look_cameras';

function domainOf(): string {
  const field = settings.value?.settings.find((s) => s.key === KEY)?.field;
  return field?.type === 'entity_list' ? (field.domains[0] ?? '') : '';
}

export function CamerasSection({ house }: { house: House }) {
  const lines = cameraLines(house, idsOf(draft.value, KEY), domainOf());
  return (
    <section class="panel cn-set">
      <div class="cn-set-head"><h2>Cameras she may look through</h2></div>
      <p class="cn-blurb">A camera that is on here is one she can look through when someone asks: she takes one still, sees it and keeps it with the message. She never looks on her own, and a camera that is off is not even in her list. With none on she has no cameras.</p>
      {lines.length === 0
        ? <p class="set-empty">No cameras found.</p>
        : (
          <ul class="set-rows">
            {lines.map((l) => (
              <Row key={l.id} name={l.name} sub={l.sub} note={l.missing ? 'Not found there right now' : null}>
                <Switch label="She may look through it" checked={l.only}
                  onChange={() => edit(withIds(draft.value, KEY, '', toggled(idsOf(draft.value, KEY), l.id)))} />
              </Row>
            ))}
          </ul>
        )}
    </section>
  );
}
