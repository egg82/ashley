// A bench job's card, written by the job runner: who works on it, what state it is in, when it began and must end, the
// pieces it made, and a Cancel while it is still going. A body that is not a job's is shown as the text it is.
import { useState } from 'preact/hooks';
import { cancelJob } from '../../../api/jobs';
import { moment } from '../../memory/facts';

type Job = { job: number | null; worker: string; state: string; started: string | null; deadline: string | null; finished: string | null; outputs: number[]; files_refused: number; reason: string | null };

const STATES: Record<string, string> = { due: 'Waiting to start', waiting: 'Waiting for your machine', starting: 'Starting', running: 'Working', blocked: 'Waiting for you', done: 'Done', failed: 'Failed', timed_out: 'Ran out of time', cancelled: 'Cancelled' };
const WORKERS: Record<string, string> = { agent: 'Ashley’s worker', claude_code: 'Your Claude Code' };
const ENDED = ['done', 'failed', 'timed_out', 'cancelled'];

function parsed(body: string): Job | null {
  try {
    const got: unknown = JSON.parse(body);
    return got && typeof got === 'object' && !Array.isArray(got) ? (got as Job) : null;
  } catch {
    return null;
  }
}

export function JobView({ bench, body, closed }: { bench: number; body: string; closed: boolean }) {
  const job = parsed(body);
  const [busy, setBusy] = useState(false);
  if (!job) return <div class="pbody plain"><p>{body}</p></div>;
  const ended = ENDED.includes(job.state);
  const stop = () => {
    if (job.job === null) return;
    setBusy(true);
    void cancelJob(bench, job.job).finally(() => setBusy(false));
  };
  return (
    <div class="pbody auto">
      <p class="rline">
        <span class={`rstate${job.state === 'done' ? ' ok' : ended ? ' bad' : ''}`}>{STATES[job.state] ?? job.state}</span>
        <span class="meta"> · {WORKERS[job.worker] ?? job.worker}{job.started ? ` · began ${moment(job.started)}` : ''}{job.finished ? ` · ended ${moment(job.finished)}` : job.deadline ? ` · stops by ${moment(job.deadline)}` : ''}</span>
        {!ended && !closed && job.job !== null && <button class="btn sm ghost" type="button" disabled={busy} onClick={stop}>{busy ? 'Cancelling…' : 'Cancel'}</button>}
      </p>
      {job.outputs.length > 0 && <p class="meta">Made {job.outputs.length === 1 ? 'piece' : 'pieces'} {job.outputs.join(', ')}</p>}
      {job.files_refused > 0 && <p class="meta">{job.files_refused} returned {job.files_refused === 1 ? 'file was' : 'files were'} not taken</p>}
    </div>
  );
}
