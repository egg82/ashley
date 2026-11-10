// One fact as a card: its tab, what it replaced, where it came from, and what a person can do to it.
// A card made by a correction plays the supersede on arrival; a forgotten card greys, shrinks and collapses out.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { MemoryFact } from '../../api/types';
import { Kind, Vis } from '../../components/FactParts';
import { pause, reduced } from '../../shell/motion';
import { CorrectEditor } from './CorrectEditor';
import { person } from '../../session/session';
import { day, moment, moveOf, sourceLabel, whereLabel } from './facts';
import { HoldToForget } from './HoldToForget';
import { correct, forget, move, remove, selected, type Outcome } from './memory';

type Phase = 'idle' | 'editing' | 'saving' | 'forgetting' | 'gone';

const FAILED: Record<Exclude<Outcome, 'ok' | 'gone'>, string> = {
  unreachable: "Can't reach her. Nothing changed.",
  failed: "That didn't go through. Nothing changed.",
};

/** Greys and shrinks (CSS, `--t-panel`), then folds its height away; reduced motion skips the fold. */
async function collapse(el: HTMLElement): Promise<void> {
  await pause(420);
  if (reduced()) return;
  await el.animate([{ height: `${el.offsetHeight}px` }, { height: '0px', paddingTop: '0px', paddingBottom: '0px', marginBottom: '-12px' }], {
    duration: 300,
    easing: 'cubic-bezier(.5,0,.9,.4)',
  }).finished;
}

function Replaced({ fact }: { fact: MemoryFact }) {
  if (!fact.replaced) return null;
  return (
    <div class="was">
      <s>{fact.replaced.text}</s> · until {day(fact.replaced.valid_to)}
    </div>
  );
}

function Foot({ fact }: { fact: MemoryFact }) {
  return (
    <div class="foot">
      <span class="meta">since {day(fact.valid_from)}</span>
      <span class="src meta">
        {sourceLabel(fact.source)} · {moment(fact.source.started_at)}
        {whereLabel(fact.source) && ` · ${whereLabel(fact.source)}`}
        {!fact.source.took_part && " · you weren't in it"}
      </span>
    </div>
  );
}

export function FactCard({ fact, fresh, onClose }: { fact: MemoryFact; fresh: boolean; onClose?: () => void }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const el = useRef<HTMLElement>(null);
  // A row opened into this card: focus follows it, since the row's button is gone.
  useEffect(() => void (onClose && el.current?.focus()), []);
  const setTide = (p: number) => el.current?.style.setProperty('--p', String(p));
  const holding = (p: number) => {
    setTide(p);
    el.current?.classList.toggle('holding', p > 0);
  };

  const save = async (text: string) => {
    setPhase('saving');
    const outcome = await correct(fact.id, text);
    if (outcome === 'ok' || outcome === 'gone') return;
    setError(FAILED[outcome]);
    setPhase('editing');
  };
  const moveTo = moveOf(fact, person.value?.id);
  const moveNow = async (to: 'household' | 'mine') => {
    setPhase('saving');
    setError(null);
    const outcome = await move(fact.id, to);
    if (outcome === 'ok' || outcome === 'gone') return;
    setError(FAILED[outcome]);
    setPhase('idle');
  };
  const forgetNow = async () => {
    setPhase('forgetting');
    setError(null);
    const outcome = await forget(fact.id);
    if (outcome === 'gone') return;
    if (outcome !== 'ok') {
      holding(0);
      setError(FAILED[outcome]);
      setPhase('idle');
      return;
    }
    setPhase('gone');
    if (el.current) await collapse(el.current);
    remove(fact.id);
  };

  const editing = phase === 'editing' || phase === 'saving';
  const busy = phase === 'saving' || phase === 'forgetting' || phase === 'gone';
  return (
    <article
      ref={el}
      class={`fact card${fresh ? ' superseded' : ''}${phase === 'gone' ? ' gone' : ''}${phase === 'forgetting' ? ' holding' : ''}${selected.value === fact.id ? ' sel' : ''}`}
      data-kind={fact.kind}
      tabIndex={-1}
      onClick={(e) => !(e.target as Element).closest('button, input, form') && (selected.value = fact.id)}
    >
      <Kind kind={fact.kind} named />
      <Vis v={fact.visibility} />
      {editing ? (
        <CorrectEditor text={fact.text} saving={phase === 'saving'} onSave={(t) => void save(t)} onCancel={() => (setPhase('idle'), setError(null))} />
      ) : (
        <span class="text">{fact.text}</span>
      )}
      <Replaced fact={fact} />
      <Foot fact={fact} />
      {error && <div class="err" role="alert">{error}</div>}
      {!editing && (
        <div class="acts">
          <button class="btn sm correct" type="button" disabled={busy} onClick={() => (setPhase('editing'), setError(null))}>Correct</button>
          {moveTo && (
            <button class="btn sm move" type="button" disabled={busy} onClick={() => void moveNow(moveTo)}>
              {moveTo === 'household' ? "Make it the household's" : 'Make it mine'}
            </button>
          )}
          <HoldToForget disabled={busy} onProgress={holding} onDone={() => void forgetNow()} />
          {onClose && <button class="btn sm ghost close" type="button" onClick={onClose}>Close</button>}
          <span class="hold-says meta" aria-hidden="true">Gone for good when the ring fills. Let go to keep it.</span>
        </div>
      )}
    </article>
  );
}
