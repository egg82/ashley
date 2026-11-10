// A script she ran for an answer, under that answer: closed it says what ran and how it ended; open it shows the
// script, its input, what it printed and the files it left. Native <details>, so it opens from the keyboard.
import type { ChatRun } from '../../api/types';

const LANGUAGE: Record<ChatRun['language'], string> = { python: 'Python', build123d: 'build123d' };

/** How the run ended, in the words the closed summary uses. */
export function ending(run: ChatRun): string {
  switch (run.result) {
    case 'ran': return `exit ${run.exit_code ?? '?'}`;
    case 'timed_out': return 'timed out';
    case 'out_of_memory': return 'out of memory';
    case 'failed': return 'failed to run';
    case 'unknown': return 'outcome unknown';
    case null: return 'no result recorded';
  }
}

function Block({ label, text }: { label: string; text: string }) {
  return (
    <div class="run-part">
      <div class="run-label">{label}</div>
      <pre class="run-pre" tabIndex={0}>{text}</pre>
    </div>
  );
}

function Printed({ run }: { run: ChatRun }) {
  if (run.result === null) return null;
  const nothing = !run.stdout && !run.stderr;
  return (
    <>
      {run.stdout && <Block label="Output" text={run.stdout} />}
      {run.stderr && <Block label="Errors" text={run.stderr} />}
      {nothing && <div class="run-part"><div class="run-label">Output</div><p class="run-none">Nothing printed.</p></div>}
      {run.cut && <p class="run-none">Cut to the sandbox's limit.</p>}
    </>
  );
}

function Files({ run }: { run: ChatRun }) {
  if (!run.made.length && !run.skipped.length) return null;
  return (
    <div class="run-part">
      <div class="run-label">Files</div>
      {run.made.map((f) => (
        <details class="run-file" key={f.name} open={run.made.length === 1}>
          <summary>{f.name}</summary>
          <pre class="run-pre" tabIndex={0}>{f.text}</pre>
        </details>
      ))}
      {run.skipped.length > 0 && <p class="run-none">Left out: {run.skipped.join(', ')}</p>}
    </div>
  );
}

export function RunDetails({ run }: { run: ChatRun }) {
  const good = run.result === 'ran' && run.exit_code === 0;
  return (
    <details class="run">
      <summary>
        <span class={`run-dot${good ? ' ok' : ''}`} aria-hidden="true" />
        {run.result === null ? LANGUAGE[run.language] : `Ran ${LANGUAGE[run.language]}`} · {ending(run)}
      </summary>
      <Block label="Script" text={run.script} />
      {run.stdin && <Block label="Input" text={run.stdin} />}
      <Printed run={run} />
      <Files run={run} />
    </details>
  );
}
