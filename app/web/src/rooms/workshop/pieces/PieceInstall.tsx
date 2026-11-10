// An automation piece's install strip: her proposal waiting on the person, with the button that approves it (an
// `install` command), and what the latest install or undo of one did to Home Assistant, with a button to take an
// install back out (an `undo` of it). A record with no ending says so, never a blank.
import { useState } from 'preact/hooks';
import type { BenchPiece, InstallProposal, InstallState } from '../../../api/types';
import { moment } from '../../memory/facts';
import { apply } from '../model/bench';

const ENDED: Record<NonNullable<InstallState['install_ending']>, string> = { done: 'done', refused: 'refused', failed: 'failed' };

function Proposal({ piece, proposal, busy, go }: { piece: BenchPiece; proposal: InstallProposal; busy: boolean; go: (f: () => Promise<unknown>) => void }) {
  return (
    <p class="rline">
      <span class="pill her-meta">Ashley proposes</span>
      <span class="meta"> installing it {proposal.enabled ? 'enabled' : 'disabled'}{proposal.turn_off ? `, turning off ${proposal.turn_off}` : ''}</span>
      <button class="btn sm primary pinstall-go" type="button" disabled={busy}
        onClick={() => go(() => apply({ type: 'install', piece_id: piece.id, proposal: proposal.seq }))}>
        {busy ? 'Installing…' : 'Install'}
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

export function InstallStrip({ piece, closed }: { piece: BenchPiece; closed: boolean }) {
  const [busy, setBusy] = useState(false);
  const shown = piece.automation;
  const go = (f: () => Promise<unknown>) => {
    setBusy(true);
    void f().finally(() => setBusy(false));
  };
  const proposal = shown?.install_proposal;
  const last = shown?.last_install;
  return (
    <section class="prun pinstall" aria-label={`Installing ${piece.title}`} aria-busy={busy}>
      {proposal && !closed && <Proposal piece={piece} proposal={proposal} busy={busy} go={go} />}
      {last ? <Last last={last} busy={busy || closed} go={go} /> : !proposal && <p class="meta">Not installed</p>}
    </section>
  );
}
