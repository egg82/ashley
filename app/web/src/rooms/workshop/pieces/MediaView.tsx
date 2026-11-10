// A clip or audio piece: the bytes are kept by the server and played from their short-lived link (`piece.file.url`),
// which answers byte ranges so the player's own controls scrub. Nothing autoplays; Ashley's cue (play, pause, seek,
// `player.ts`) drives the element while the page is open, and a line under the player says what she did, as text, so
// it needs no motion.
import { useEffect, useRef, useState } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { onBenchCue } from '../../../session/live';
import { cueText } from '../model/clock';
import { setPlayhead } from '../model/playhead';
import { bytesText, typeText } from '../model/size';
import { driveFile, type Cue } from './player';

type Player = HTMLVideoElement | HTMLAudioElement;

function useCues(bench: number, piece: number): { player: { current: Player | null }; said: string } {
  const player = useRef<Player | null>(null);
  const [said, setSaid] = useState('');
  useEffect(() => onBenchCue((b, p, cue: Cue, by) => {
    if (b !== bench || p !== piece) return;
    if (player.current) driveFile(player.current, cue);
    if (by === 'her') setSaid(cueText(cue));
  }), [bench, piece]);
  useEffect(() => () => setPlayhead(bench, piece, null), [bench, piece]);
  return { player, said };
}

/** The player's place, told to whoever follows it (a transcript beside it). */
function follow(bench: number, piece: number) {
  const tell = (e: Event) => {
    const el = e.currentTarget as Player;
    setPlayhead(bench, piece, { seconds: el.currentTime, playing: !el.paused && !el.ended });
  };
  return { onTimeUpdate: tell, onPlay: tell, onPause: tell, onSeeked: tell, onEnded: tell };
}

function Unreachable({ piece }: { piece: BenchPiece }) {
  const file = piece.file;
  if (!file) return <div class="pbody"><span class="unk">not a recording this page can play</span></div>;
  return (
    <div class="pbody pfile">
      <span class="pfile-name">{file.name}</span>
      <span class="meta">{bytesText(file.size_bytes)} · {typeText(file.media_type)} · can't be reached right now</span>
    </div>
  );
}

export function MediaView({ bench, piece, video }: { bench: number; piece: BenchPiece; video: boolean }) {
  const cues = useCues(bench, piece.id);
  const file = piece.file;
  if (!file?.url) return <Unreachable piece={piece} />;
  return (
    <div class="pbody pmedia">
      {video ? (
        <video class="frame-box file" controls preload="metadata" playsInline title={file.name} src={file.url}
          ref={cues.player as { current: HTMLVideoElement | null }} {...follow(bench, piece.id)} />
      ) : (
        <audio class="pmedia-audio" controls preload="metadata" title={file.name} src={file.url}
          ref={cues.player as { current: HTMLAudioElement | null }} {...follow(bench, piece.id)} />
      )}
      <div class="pfile-row">
        <span class="pfile-text">
          <span class="pfile-name">{file.name}</span>
          <span class="meta">{bytesText(file.size_bytes)} · {typeText(file.media_type)}</span>
        </span>
        <a class="btn sm" href={file.url} download={file.name}>Download</a>
      </div>
      <p class="meta pmedia-cue" role="status" aria-live="polite">{cues.said}</p>
    </div>
  );
}
