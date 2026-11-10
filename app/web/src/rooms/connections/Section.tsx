// The two sections of the room, Yours and The household's, each a panel of compact rows.
import type { ComponentChildren } from 'preact';
import { accounts } from './accounts';
import { connectionsState, held, kinds, loadConnections } from './connections';
import { AccountRow, DiscordRow, KindRow } from './Rows';

/** Whether the connections were read, so an empty list is a fact and not a wait or a failure. */
function settled(): boolean {
  return connectionsState.value === 'ready';
}

function Section({ title, count, empty, children }: { title: string; count: number; empty: string; children: ComponentChildren }) {
  return (
    <section class="cn-sec">
      <div class="cn-sec-head"><h2 class="label">{title}</h2>{count > 0 && <span class="meta">{count}</span>}</div>
      <div class="panel cn-list">
        {children}
        {count === 0 && settled() && <p class="meta cn-empty">{empty}</p>}
      </div>
    </section>
  );
}

/** Why the kinds' rows are not there yet, or null when they are (or cannot be). */
function Unread() {
  switch (connectionsState.value) {
    case 'loading':
      return <p class="meta cn-empty">Reading the connections…</p>;
    case 'failed':
      return (
        <div class="cn-empty dc-act">
          <span class="unk">couldn’t read the connections</span>
          <button class="btn sm ghost" type="button" onClick={() => void loadConnections()}>Try again</button>
        </div>
      );
    case 'off':
      return <div class="cn-empty"><span class="unk">services can’t be connected here</span></div>;
    case 'ready':
      return null;
  }
}

function kindRows(personal: boolean) {
  return held.value.flatMap((c) => {
    const kind = kinds.value.find((k) => k.name === c.kind);
    return kind && c.personal === personal ? [<KindRow key={c.id} kind={kind} c={c} />] : [];
  });
}

export function Yours() {
  const discord = accounts.value.filter((a) => a.system === 'discord');
  const others = accounts.value.filter((a) => a.system !== 'discord');
  const kindsHeld = kindRows(true);
  return (
    <Section title="Yours" count={discord.length + kindsHeld.length + others.length} empty="Nothing of yours is connected yet.">
      {discord.map((a) => <DiscordRow key={a.id} account={a} />)}
      {kindsHeld}
      {others.map((a) => <AccountRow key={a.id} account={a} />)}
      {connectionsState.value !== 'off' && <Unread />}
    </Section>
  );
}

export function Household() {
  const held = kindRows(false);
  return (
    <Section title="The household’s" count={held.length} empty="Nothing connected for the household yet.">
      {held}
      <Unread />
    </Section>
  );
}
