// Devices, at bearing 070: this device's notifications, and the household's devices and pronunciation words beside them.
import type { ComponentChildren } from 'preact';
import { useEffect, useLayoutEffect, useRef } from 'preact/hooks';
import type { ListedDevice } from '../../api/types';
import { dockIn } from '../../shell/her/dock';
import { ControlsEditor } from './ControlsEditor';
import { showsControls } from './controlRows';
import { loadLights } from './controls';
import { devices, devicesState, leaveRoom, loadDevices } from './devices';
import { Lexicon } from './Lexicon';
import { loadLexicon } from './lexiconWords';
import { loadPush, push, pushBusy, pushSaid, turnOff, turnOn } from './notifications';

type PushSaid = NonNullable<typeof pushSaid.value>;

const PUSH_NOTE: Record<PushSaid, [string, 'ok' | 'bad' | '']> = {
  on: ['Turned on for this device.', 'ok'],
  off: ['Turned off for this device.', 'ok'],
  denied: ["The browser didn't ask, or wasn't allowed to. Nothing changed.", 'bad'],
  failed: ["That didn't go through. Nothing changed.", 'bad'],
  unreachable: ["Can't reach her right now. Nothing changed.", 'bad'],
};

const IPHONE = 'On iPhone, add her to the Home Screen first (Share, then Add to Home Screen) and turn this on from there.';

function PushNote() {
  const s = pushSaid.value;
  if (!s) return null;
  const [text, tone] = PUSH_NOTE[s];
  return (
    <div class={`dc-note ${tone}`} role="status">
      <span>{text}</span>
      <button class="btn sm ghost" type="button" onClick={() => (pushSaid.value = null)}>Dismiss</button>
    </div>
  );
}

function Cannot({ why, children }: { why: string; children?: ComponentChildren }) {
  return (
    <>
      <div class="dc-act">
        <button class="btn primary" type="button" disabled>Turn on</button>
        <span class="unk">{why}</span>
      </div>
      {children}
    </>
  );
}

function PushControl() {
  switch (push.value) {
    case 'loading':
      return <p class="meta">Checking this device…</p>;
    case 'on':
      return (
        <div class="dc-done">
          <div>
            <b>On for this device</b>
            <div class="meta">Links and lists she mentions aloud land here</div>
          </div>
          <button class="btn sm ghost" type="button" disabled={pushBusy.value} onClick={() => void turnOff()}>Turn off</button>
        </div>
      );
    case 'off':
      return (
        <>
          <p>When a link or a list is better read than heard, she can send it here.</p>
          <div class="dc-act">
            <button class="btn primary" type="button" disabled={pushBusy.value} onClick={() => void turnOn()}>Turn on</button>
            {pushBusy.value && <span class="meta">Asking the browser…</span>}
          </div>
          <p class="meta">{IPHONE}</p>
        </>
      );
    case 'unsupported':
      return <Cannot why="not in this browser"><p class="meta">{IPHONE}</p></Cannot>;
    case 'unavailable':
      return <Cannot why="not set up here" />;
    case 'blocked':
      return (
        <Cannot why="blocked by the browser">
          <p class="meta">Allow notifications for this site in the browser's settings, then come back.</p>
        </Cannot>
      );
    case 'failed':
      return (
        <div class="dc-act">
          <span class="unk">couldn't check this device</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadPush()}>Try again</button>
        </div>
      );
  }
}

function Notifications() {
  return (
    <div class="panel">
      <div class="ph"><h3>Notifications on this device</h3></div>
      <div class="dc-body">
        <PushControl />
        <PushNote />
      </div>
    </div>
  );
}

const FORM: Record<ListedDevice['form'], string> = { satellite: 'Satellite', discord_server: 'Discord server', house: 'Home Assistant', other: 'Other' };
const AUDIENCE: Record<ListedDevice['audience'], string> = { owner: 'Only its owner', household: 'The household', present: 'Whoever is there' };

function Device({ d }: { d: ListedDevice }) {
  return (
    <>
      <div class="acct-row">
        <b>{d.name}</b>
        <span class="pill">{FORM[d.form]}</span>
        <span class="meta">{d.place} · {AUDIENCE[d.audience]} · {d.medium}</span>
      </div>
      {showsControls(d) && <ControlsEditor d={d} />}
    </>
  );
}

function DeviceList() {
  switch (devicesState.value) {
    case 'loading':
      return <div class="devs-body"><span class="meta">Reading the devices…</span></div>;
    case 'failed':
      return (
        <div class="devs-body">
          <span class="unk">couldn't read the devices</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadDevices()}>Try again</button>
        </div>
      );
    case 'ready':
      return devices.value.length ? <>{devices.value.map((d) => <Device key={d.id} d={d} />)}</> : (
        <div class="devs-body"><p class="meta">No devices are set up for this household yet.</p></div>
      );
  }
}

export function DevicesRoom() {
  useEffect(() => {
    void loadPush();
    void loadDevices();
    void loadLexicon();
    void loadLights();
    return leaveRoom;
  }, []);
  const here = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const room = here.current?.closest('.room');
    if (room && !room.classList.contains('leaving')) dockIn(room, false);
  }, []);
  return (
    <div class="set" ref={here}>
      <div class="set-head">
        <h1>Devices</h1>
        <span class="set-dock" data-dock />
      </div>
      <div class="set-grid">
        <div class="set-col">
          <Notifications />
        </div>
        <div class="set-col">
          <div class="panel devs">
            <div class="ph"><h3>Where to find her</h3></div>
            <DeviceList />
          </div>
          <Lexicon />
        </div>
      </div>
    </div>
  );
}
