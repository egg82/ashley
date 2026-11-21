// An automation piece's install strip: her proposal waiting on the person, with the button that approves it (an
// `install` command), and what the latest install or undo of one did to Home Assistant, with a button to take an
// install back out (an `undo` of it). A record with no ending says so, never a blank. A shadow run of the piece shows
// beside them: when it would have fired next to when the automation it would replace did, and a button to stop it.
import { useState } from 'preact/hooks';
import type { BenchPiece, InstallProposal, InstallState, ShadowState } from '../../../api/types';
import { moment } from '../../memory/facts';
import { apply } from '../model/bench';

const ENDED: Record<NonNullable<InstallState['install_ending']>, string> = { done: 'done', refused: 'refused', failed: 'failed' };

function Proposal({ piece, proposal, busy, go }: { piece: BenchPiece; proposal: InstallProposal; busy: boolean; go: (f: () => Promise<unknown>) => void }) {
  return (
    <p class="rline">
      <span class="pill her-meta">Ashley proposes</span>
      <span class="meta"> {proposal.shadow
        ? `a shadow run: it records when it would have fired and changes nothing${proposal.turn_off ? `, beside ${proposal.turn_off}` : ''}`
        : `installing it ${proposal.enabled ? 'enabled' : 'disabled'}${proposal.turn_off ? `, turning off ${proposal.turn_off}` : ''}`}</span>
      <button class="btn sm primary pinstall-go" type="button" disabled={busy}
        onClick={() => go(() => apply({ type: 'install', piece_id: piece.id, proposal: proposal.seq }))}>
        {busy ? 'Installing…' : proposal.shadow ? 'Start shadow run' : 'Install'}
      </button>
    </p>
  );
}

function Last({ last, busy, go }: { last: InstallState; busy: boolean; go: (f: () => Promise<unknown>) => void }) {
  const end = last.install_ending;
  const what = last.action === 'install'
    ? `Installed as ${last.automation_id}${last.enabled === null ? '' : last.enabled ? ', enabled' : ', disabled'}`
    : `Taken out of Home Assistant${last.turn_off ? `, ${last.turn_off} back on` : ''}`;
  const undoable = last.action === 'install' && end !== 'refused';
  return (
    <>
      <p class="rline">
        <span class={`rstate${end === 'done' ? ' ok' : end ? ' bad' : ''}`}>{end ? ENDED[end] : 'No ending recorded'}</span>
        <span class="meta"> · {what} · {moment(last.finished_at ?? last.started_at)}</span>
        {undoable && (
          <button class="btn sm ghost pinstall-go" type="button" disabled={busy}
            onClick={() => go(() => apply({ type: 'undo', seq: last.seq }))}>Take it out</button>
        )}
      </p>
      {last.install_note && <p class="meta">{last.install_note}</p>}
      {!end && <p class="meta">Check it in Home Assistant: it may be partly changed.</p>}
    </>
  );
}

function Shadow({ run, busy, go }: { run: ShadowState; busy: boolean; go: (f: () => Promise<unknown>) => void }) {
  const times = (kind: 'would' | 'did') => run.firings.filter((f) => f.kind === kind);
  const kept = (kind: 'would' | 'did') => (kind === 'would' ? run.would : run.did);
  return (
    <>
      <p class="rline">
        {run.ended_at ? <b>Shadow run ended</b> : <span class="rstate ok">Shadow run</span>}
        <span class="meta"> · {run.ended_at ? `ended ${moment(run.ended_at)}` : `ends ${moment(run.ends_at)}`} · piece version {run.piece_version}</span>
        {!run.ended_at && (
          <button class="btn sm ghost pinstall-go" type="button" disabled={busy}
            onClick={() => go(() => apply({ type: 'undo', seq: run.seq }))}>Stop it</button>
        )}
      </p>
      {(['would', 'did'] as const).filter((kind) => kind === 'would' || run.replaces).map((kind) => (
        <div class="auto-sec" key={kind}>
          <b>{kind === 'would' ? 'Would' : 'Did'}</b>
          {times(kind).length ? (
            <ul aria-label={kind === 'would' ? 'When the piece would have fired' : 'When the automation it replaces fired'}>
              {times(kind).map((f) => <li key={f.at}>{moment(f.at)}</li>)}
              {kept(kind) > times(kind).length && <li class="meta">and {kept(kind) - times(kind).length} earlier</li>}
            </ul>
          ) : (
            <span class="meta">{kind === 'would' ? 'It has not fired yet' : 'It has not been triggered yet'}</span>
          )}
        </div>
      ))}
    </>
  );
}

export function InstallStrip({ piece, closed }: { piece: BenchPiece; closed: boolean }) {
  const [busy, setBusy] = useState(false);
  const shown = piece.automation;
  const go = (f: () => Promise<unknown>) => {
    setBusy(true);
    void f().finally(() => setBusy(false));
  };
  const proposal = shown?.install_proposal;
  const last = shown?.last_install;
  const shadow = shown?.shadow_run;
  return (
    <section class="prun pinstall" aria-label={`Installing ${piece.title}`} aria-busy={busy}>
      {proposal && !closed && <Proposal piece={piece} proposal={proposal} busy={busy} go={go} />}
      {last ? <Last last={last} busy={busy || closed} go={go} /> : !proposal && !shadow && <p class="meta">Not installed</p>}
      {shadow && <Shadow run={shadow} busy={busy || closed} go={go} />}
      {shown?.unanswered_events.map((event) => (
        <p key={event} class="meta rline"><span class="rstate bad">No wake rule</span> It sends <b>{event}</b>, and no wake rule on an open bench answers it.</p>
      ))}
    </section>
  );
}
