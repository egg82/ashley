// Devices, at bearing 070: the household's devices drawn as a house and said in words, the selected one with its touch
// controls, and this browser's notifications.
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import { herWord } from '../../shell/her/state';
import { dockIn } from '../../shell/her/dock';
import { DevicePanel } from './DevicePanel';
import { devices, devicesState, leaveRoom, loadDevices, loadLinked, selected } from './devices';
import { FloorPlan } from './FloorPlan';
import { LinkedAccounts } from './LinkedAccounts';
import { loadLights } from './controls';
import { loadPush } from './notifications';
import { placeCount, planOf } from './plan';
import { PlaceRows } from './PlaceRows';
import { Notifications } from './PushPanel';

function Down({ failed }: { failed: boolean }) {
  return (
    <div class="panel set-down" role="alert">
      <span class="down-dock" data-dock />
      <div class="set-down-says">
        {!failed && <span class="her-word unreachable">{herWord.value}</span>}
        <b>{failed ? "The devices didn't load." : "Can't reach her right now."}</b>
        <button class="btn" type="button" onClick={() => void loadDevices()}>Try again</button>
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div class="panel dv-empty">
      <b>No devices yet.</b>
      <p class="meta">A satellite, a screen or a Discord server she listens through shows up here once it is set up for this household.</p>
    </div>
  );
}

function Count({ n, places }: { n: number; places: number }) {
  return <span class="meta dv-count">{n} {n === 1 ? 'device' : 'devices'} · {places} {places === 1 ? 'place' : 'places'}</span>;
}

function Body() {
  const list = devices.value;
  const plan = planOf(list);
  const chosen = list.find((d) => d.id === selected.value);
  return (
    <div class="set-grid dv-grid">
      <div class="set-col">
        <FloorPlan plan={plan} />
        <PlaceRows plan={plan} />
      </div>
      <div class="set-col">
        {chosen && <DevicePanel d={chosen} />}
        <Notifications />
        <LinkedAccounts />
      </div>
    </div>
  );
}

export function DevicesRoom() {
  useEffect(() => {
    void loadPush();
    void loadDevices();
    void loadLights();
    void loadLinked();
    return leaveRoom;
  }, []);
  const here = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, []);
  const state = devicesState.value;
  const down = state === 'unreachable' || state === 'failed';
  const plan = planOf(devices.value);
  return (
    <div class="set dvs" ref={here}>
      <div class="set-head">
        <h1>Devices</h1>
        {state === 'ready' && devices.value.length > 0 && <Count n={devices.value.length} places={placeCount(plan)} />}
        {!down && <span class="set-dock" data-dock />}
      </div>
      {down && <><Down failed={state === 'failed'} /><div class="dv-solo"><Notifications /></div></>}
      {state === 'loading' && <p class="meta" role="status">Reading the devices…</p>}
      {state === 'ready' && (devices.value.length === 0 ? <><Empty /><div class="dv-solo"><Notifications /></div></> : <Body />)}
    </div>
  );
}
