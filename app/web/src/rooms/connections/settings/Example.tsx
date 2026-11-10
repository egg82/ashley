// A short worked example opening a section: what she will do (a tick) and what she will not (a cross).
export interface Case {
  does: boolean;
  text: string;
}

export function Example({ cases }: { cases: readonly Case[] }) {
  return (
    <div class="set-ex">
      <span class="label">For example</span>
      {cases.map((c) => <span key={c.text} class={c.does ? 'ok' : 'no'}>{c.text}</span>)}
    </div>
  );
}
