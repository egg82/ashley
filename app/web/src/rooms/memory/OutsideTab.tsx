// The "On her own" tab: each change she made for the person with no OK after reading words from outside the household,
// newest first: when, its headline and what changed, and for a judged one the judge's reason.
import type { OutsideAction } from '../../api/types';
import { doneAt, loadOutside, NO_LABEL, NO_REASON, outside, outsideState, TIER } from './outside';

function Row({ a }: { a: OutsideAction }) {
  return (
    <div class={`fact did ${a.tier}`} data-kind="plan">
      <span class="did-when">{doneAt(a.at)}</span>
      <span class="did-what">{a.label ?? NO_LABEL}</span>
      <span class="pill">{TIER[a.tier]}</span>
      <span class="meta did-summary">{a.summary}</span>
      {a.tier === 'judged' && <span class={`did-why${a.explanation ? '' : ' meta'}`}>{a.explanation ?? NO_REASON}</span>}
    </div>
  );
}

export function OutsideList() {
  const state = outsideState.value;
  if (state === 'loading') return <p class="mem-none meta">Reading what she did…</p>;
  if (state !== 'ready') {
    return (
      <div class="panel mem-down" role="alert">
        <div class="mem-down-says">
          <b>{state === 'failed' ? "What she did didn't load." : "Can't reach what she did right now."}</b>
          <button class="btn" type="button" onClick={() => void loadOutside()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!outside.value.length) {
    return (
      <div class="mem-empty">
        <div class="mem-down-says">
          <b>She hasn't changed anything on her own.</b>
          <span class="meta">Changes she makes after reading a page or an email, with no OK from you, show up here.</span>
        </div>
      </div>
    );
  }
  return (
    <>
      <div class="sec-title"><b>She did these on her own</b><span class="label">newest first</span></div>
      <div class="rows">{outside.value.map((a) => <Row key={a.id} a={a} />)}</div>
    </>
  );
}
