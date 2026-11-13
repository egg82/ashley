// Notifications on this device: turning this browser's push on or off, and what that came to.
import type { ComponentChildren } from 'preact';
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

export function Notifications() {
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
