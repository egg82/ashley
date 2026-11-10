// What answered while she loaded. Each line is something this client checked.
import { health, person } from '../session/session';
import { ticked } from './reveal';

interface Line {
  text: string;
  /** Shown beside an answered line, at meta weight. */
  meta?: string;
  /** Why the line has no answer; renders as an unknown. */
  unknown?: string;
}

export function loadingLines(): Line[] {
  return [
    { text: `Signed in as ${person.value?.name ?? ''}` },
    { text: 'Ashley', meta: health.value ? `answered · ${health.value.version}` : undefined },
  ];
}

export function LoadingLines() {
  const shown = ticked.value;
  return (
    <ol class="si-steps" aria-live="polite">
      {loadingLines().map((line, i) => (
        <li key={line.text} class={i < shown ? 'in' : undefined} data-unk={line.unknown ? '' : undefined}>
          {line.text}
          {line.meta && <span class="meta">{line.meta}</span>}
          {line.unknown && <span class="unk">{line.unknown}</span>}
        </li>
      ))}
    </ol>
  );
}
