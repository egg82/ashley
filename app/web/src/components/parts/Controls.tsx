// Touch controls: one big button each, carried out by her tools. A press shows running, then done or failed for a
// moment; none set, and controls that could not be read, read as such. A button that toggles a light says whether it
// is on, or nothing when the house could not say.
import type { ControlState, ControlsSource } from './sources';

const SHOWN: Record<ControlState, string> = { running: '…', done: 'Done', failed: "Didn't work", busy: 'Too many, wait' };

export function Controls({ source }: { source: ControlsSource }) {
  const read = source.controls.value;
  const all = read ?? [];
  const states = source.states.value;
  return (
    <section class="k-controls" aria-label="Controls">
      <h2 class="label">Controls</h2>
      {read === undefined && <span class="meta">Reading…</span>}
      {read === null && <span class="unk">couldn't read</span>}
      {read && !read.length && <span class="unk">none set</span>}
      <div class="k-grid">
        {all.map((c) => {
          const state = states[c.name];
          const lit = c.on === null ? null : c.on ? 'On' : 'Off';
          return (
            <button
              key={c.name}
              type="button"
              class={`k-control${state ? ` ${state}` : ''}${c.on ? ' lit' : ''}`}
              aria-pressed={c.on ?? undefined}
              disabled={state === 'running'}
              onClick={() => void source.press(c.name)}
            >
              <span>{c.label}</span>
              {state ? <span class="k-control-state" role="status">{SHOWN[state]}</span>
                : lit && <span class="k-control-state">{lit}</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
