// Touch controls: one big button each, carried out by her tools. A press shows running, then done or failed for a
// moment; none set reads as such.
import { controls, controlStates, press, type ControlState } from './state';

const SHOWN: Record<ControlState, string> = { running: '…', done: 'Done', failed: "Didn't work", busy: 'Too many, wait' };

export function Controls() {
  const all = controls.value;
  const states = controlStates.value;
  return (
    <section class="k-controls" aria-label="Controls">
      <h2 class="label">Controls</h2>
      {!all.length && <span class="unk">none set</span>}
      <div class="k-grid">
        {all.map((c) => {
          const state = states[c.name];
          return (
            <button
              key={c.name}
              type="button"
              class={`k-control${state ? ` ${state}` : ''}`}
              disabled={state === 'running'}
              onClick={() => void press(c.name)}
            >
              <span>{c.label}</span>
              {state && <span class="k-control-state" role="status">{SHOWN[state]}</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}
