// Her room at phone width: a list, voice and quick capture first. A big hold-to-talk, the composer for a line or a link,
// attach, her thread kept short, then what waits on the person and what she is doing, and the house's controls.
import { useState } from 'preact/hooks';
import type { ComponentChildren } from 'preact';
import { drawPart, type PartSources } from '../../../components/parts/registry';
import { houseAttention, houseControls, houseHome } from '../../../session/house';
import { TalkButton, TalkLine } from '../../../speech/TalkButton';
import { Board } from '../board/Board';
import { Composer } from '../Composer';
import { Attach } from './Attach';
import { useDrops } from './useDrops';

const SOURCES: PartSources = { controls: houseControls, home: houseHome, attention: houseAttention, conversation: () => null };

/** The lanes the short list shows; the rest are one tap away on the full board. */
const SHORT = ['waiting', 'doing'] as const;

type ComposerProps = Parameters<typeof Composer>[0];

export function Pocket({ open, thread, composer }: { open: number | null; thread: ComponentChildren; composer: ComposerProps }) {
  const [held, setHeld] = useState(false);
  const [full, setFull] = useState(false);
  const drops = useDrops(composer.thread, composer.send);
  return (
    <div class={`pocket${drops.over ? ' dropping' : ''}`} {...drops.handlers}>
      <div class="pocket-talk">
        <TalkButton talk={composer.talking} disabled={composer.disabled} onHeld={setHeld} />
        <TalkLine talk={composer.talking} held={held} />
      </div>
      <Composer {...composer} voice={false} />
      <Attach disabled={composer.disabled} onFiles={(files) => void drops.files(files)} />
      <div class="pocket-thread">{thread}</div>
      <section class="pocket-board" aria-label="Board">
        <Board open={open} only={full ? undefined : SHORT} />
        <button class="btn pocket-more" type="button" aria-expanded={full} onClick={() => setFull(!full)}>
          {full ? 'Short list' : 'Full board'}
        </button>
      </section>
      <section class="house pocket-house" aria-label="House">{drawPart('controls', SOURCES)}</section>
    </div>
  );
}
