// The kiosk at /kiosk: a shared screen paired as a device, outside the person shell. Her mark and the glance on one
// side, the conversation on the other; stacked when the screen stands upright. When she has arranged the screen, her mark
// stays as a fixed frame and the pieces she chose are laid out beside it (`Board`); a layout that cannot be read or is not
// whole leaves the fixed page above. An unpaired screen shows the pairing form.
import { useEffect } from 'preact/hooks';
import { AshleyMark } from '../components/AshleyMark';
import { Announcement } from '../speech/Announcement';
import { Board } from './Board';
import { Controls } from './Controls';
import { Glance } from './Glance';
import { layout, mark, pairing, start, startFeed, startPolling } from './state';
import { Pairing } from './Pairing';
import { Talk } from './Talk';

const WORD = { idle: 'idle', listening: 'listening', thinking: 'thinking', speaking: 'speaking', unreachable: "can't reach her" };

function Her({ size = 112 }: { size?: number }) {
  const state = mark.value;
  return (
    <div class="k-her k-drift">
      <AshleyMark state={state} size={size} />
      <span class={`her-word${state === 'unreachable' ? ' unreachable' : ''}`}>{WORD[state]}</span>
    </div>
  );
}

function Down() {
  return (
    <div class="k-pair">
      <div class="panel k-pair-card">
        <AshleyMark state="unreachable" size={96} />
        <h1>Can't reach her</h1>
        <button class="btn" type="button" onClick={() => void start()}>Try again</button>
      </div>
    </div>
  );
}

export function Kiosk() {
  useEffect(() => {
    document.documentElement.dataset.room = 'kiosk';
    void start();
    return startPolling();
  }, []);
  const state = pairing.value;
  const paired = state === 'paired';
  useEffect(() => (paired ? startFeed() : undefined), [paired]);
  if (state === 'checking') return <div class="kiosk k-checking"><AshleyMark state="thinking" size={96} /></div>;
  if (state === 'unpaired') return <Pairing />;
  if (state === 'unreachable') return <Down />;
  const arranged = layout.value;
  if (arranged)
    return (
      <main class="kiosk k-laid">
        <header class="k-frame"><Her size={72} /></header>
        <Board layout={arranged} />
        <Announcement />
      </main>
    );
  return (
    <main class="kiosk">
      <section class="k-side">
        <div class="k-top">
          <Her />
          <Glance />
        </div>
        <Controls />
      </section>
      <Talk />
      <Announcement />
    </main>
  );
}
