// The bench's talk, over the foot of the canvas: the talk ribbon (`Ribbon.tsx`) and the voice bar. The bar is voice
// first: its talk button sends what the person says, and its line says what is happening, or her new answer: its words
// when it touched no piece, or which piece it is on, to fly there (the words are that piece's callout on the canvas). ⌨
// swaps the line for her room's composer, which keeps what is typed per thread, so a draft reopens it.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchDetail } from '../../../api/types';
import { TalkButton, TalkLine } from '../../../speech/TalkButton';
import { Composer } from '../../her/Composer';
import { unsentOn } from '../../her/unsent';
import { rules } from '../model/benches';
import { focusAsk } from '../canvas/state';
import { barLine } from '../model/ribbon';
import { benchTalking, retryTalk, sendTalk, talkLines, talkPieceLines, talkSending, talkState, talkThinking } from '../model/talk';
import { Ribbon } from './Ribbon';

const HINT = 'Hold the button to talk, or ⌨ to type.';

/** The turns already said when the talk was last read afresh (opening the bench, or trying again after it failed),
 *  which the bar never shows as new. */
function useFirstRead(): ReadonlySet<number> {
  const first = useRef<Set<number> | null>(null);
  if (talkState.value !== 'ready') first.current = null;
  else if (first.current === null) first.current = new Set(talkLines.value.flatMap((l) => (l.turn === undefined ? [] : [l.turn])));
  return first.current ?? new Set();
}

interface Heard {
  touched: ReadonlyMap<number, readonly number[]>;
  onBench: (id: number) => boolean;
  firstRead: ReadonlySet<number>;
  titleOf: (id: number) => string;
}

function Said({ heard, held }: { heard: Heard; held: boolean }) {
  const state = talkState.value;
  const lines = talkLines.value;
  const last = lines.at(-1);
  const hers = barLine(lines, heard.touched, heard.onBench, heard.firstRead);
  if (benchTalking.phase.value === 'listening' || benchTalking.note.value) return <TalkLine talk={benchTalking} held={held} />;
  const say = (word: string, text: string, cls = '') => <p class={`vb-text${cls}`} role="status"><span class="vb-state">{word}</span>{text}</p>;
  if (state === 'loading') return say('Reading', '');
  if (state !== 'ready') {
    return (
      <p class="vb-text" role="alert">
        <span class="vb-state">Offline</span>{state === 'failed' ? "What you've said here didn't load. " : "Can't reach Ashley right now. "}
        <button class="btn sm ghost" type="button" onClick={() => void retryTalk()}>Try again</button>
      </p>
    );
  }
  if (talkSending.value && last?.author === 'person') return say('You', last.text, ' you');
  if (talkThinking.value) return say('Thinking', '');
  if (last?.missed) return say("Didn't send", last.text, ' you');
  if (hers?.piece != null) {
    const piece = hers.piece;
    return (
      <p class="vb-text" role="status">
        <span class="vb-state">Ashley</span>
        <button class="vb-on" type="button" onClick={() => { focusAsk.value = piece; }}>On “{heard.titleOf(piece)}” →</button>
      </p>
    );
  }
  if (hers) return say('Ashley', hers.line.text);
  return say('Here', HINT);
}

function VoiceBar({ thread, heard }: { thread: string; heard: Heard }) {
  const [typing, setTyping] = useState(() => unsentOn(thread).trim() !== '');
  const [held, setHeld] = useState(false);
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (typing) bar.current?.querySelector('textarea')?.focus();
  }, [typing]);
  const down = talkState.value !== 'ready';
  return (
    <div class={`vbar${typing ? ' typing' : ''}`} ref={bar} role="group" aria-label="Talk to Ashley">
      {typing ? (
        <Composer thread={thread} disabled={talkSending.value || down} send={sendTalk} talking={benchTalking} ask="Ask Ashley about this"
          attachMax={rules.value?.kinds.find((k) => k.name === 'document')?.max_chars} />
      ) : (
        <>
          <TalkButton talk={benchTalking} disabled={talkSending.value || down} onHeld={setHeld} />
          <Said heard={heard} held={held} />
        </>
      )}
      <button class="btn sm ghost vb-type" type="button" aria-pressed={typing} aria-label={typing ? 'Talk instead' : 'Type instead'}
        title={typing ? 'Talk instead' : 'Type instead'} onClick={() => setTyping(!typing)}>⌨</button>
    </div>
  );
}

export function BenchTalk({ bench }: { bench: BenchDetail }) {
  const b = bench.bench;
  const closed = b.closed_at !== null;
  const firstRead = useFirstRead();
  const out = new Map(bench.pieces.map((p) => [p.id, p.title]));
  const onBench = (id: number) => out.has(id);
  const touched = new Map(talkPieceLines.value.map((l) => [l.turn, l.pieces]));
  const heard: Heard = { touched, onBench, firstRead, titleOf: (id) => out.get(id) ?? '' };
  return (
    <div class="talkband">
      <Ribbon closed={closed} touched={touched} onBench={onBench} />
      {!closed && <VoiceBar thread={b.thread} heard={heard} />}
    </div>
  );
}
