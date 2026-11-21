// The Your voice tab: the voiceprints she holds of the person signed in, each with the device it was enrolled on and
// when, oldest first, and one control that forgets them all, which asks once more before it acts. Only theirs: no one
// sees another's. A print is how a voice sounds to her, never a recording.
import { useState } from 'preact/hooks';
import { moment } from './facts';
import { forgetPrints, loadPrints, prints, printsState } from './voice';

function Forget() {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setBusy(true);
    const outcome = await forgetPrints();
    setBusy(false);
    setFailed(outcome !== 'ok');
    setAsking(false);
  };
  return (
    <div class="voice-acts">
      {asking ? (
        <>
          <button class="btn sm" type="button" disabled={busy} onClick={() => void go()}>Forget it all</button>
          <button class="btn sm ghost" type="button" disabled={busy} onClick={() => setAsking(false)}>Keep</button>
        </>
      ) : (
        <button class="btn sm ghost" type="button" onClick={() => setAsking(true)}>Forget my voice</button>
      )}
      {failed && <span class="err" role="alert">Couldn't forget it just now. Try again.</span>}
    </div>
  );
}

export function VoiceList() {
  const state = printsState.value;
  if (state === 'loading') return <p class="mem-none meta">Reading her voiceprints…</p>;
  if (state !== 'ready') {
    return (
      <div class="panel mem-down" role="alert">
        <div class="mem-down-says">
          <b>{state === 'failed' ? "Your voice didn't load." : "Can't reach her memory of your voice right now."}</b>
          <button class="btn" type="button" onClick={() => void loadPrints()}>Try again</button>
        </div>
      </div>
    );
  }
  if (!prints.value.length) {
    return (
      <div class="mem-empty">
        <div class="mem-down-says">
          <b>She doesn't know your voice.</b>
          <span class="meta">When you enrol on a speaker, the prints of your voice show up here.</span>
        </div>
      </div>
    );
  }
  return (
    <>
      <div class="sec-title"><b>How she tells your voice</b><span class="label">oldest first</span></div>
      <div class="rows">
        {prints.value.map((p, i) => (
          <div class="fact rem" data-kind="plan" key={i}>
            <span class="rem-when">{moment(p.enrolled_at)}</span>
            <span class="rem-what">Enrolled on {p.device}</span>
          </div>
        ))}
      </div>
      <Forget />
      <p class="mem-none meta">A print is how your voice sounds to her, not a recording. Forgetting deletes them all, and she names you by presence alone again.</p>
    </>
  );
}
