// "How she says it": the household's own units, clock and language on one example line, rewritten as they are edited.
import { sayLine } from './moment';
import { draft } from './state';
import { useNow } from './useNow';

export function SayLine() {
  const d = draft.value;
  const now = useNow(30_000);
  if (!d) return null;
  const line = sayLine(now, d.timezone, { locale: d.locale, clock: d.clock, unit_system: d.unit_system });
  return (
    <div class="panel">
      <div class="ph"><h3>How she says it</h3></div>
      <div class="dc-body">
        {line ? <p class="hh-line" aria-live="polite">{line}</p> : <p><span class="unk">can't write it with these settings</span></p>}
        <span class="meta">Example, with a made-up temperature</span>
      </div>
    </div>
  );
}
