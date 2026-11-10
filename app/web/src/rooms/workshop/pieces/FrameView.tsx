// A `live` kind's body shown in a frame: a site piece's https URL in a sandboxed iframe, a video piece's video
// (understood by the server, `piece.video`) in its provider's privacy embed or a `<video>` for a direct file. Many
// sites refuse to be framed and the page cannot tell, so the server measures it (`piece.site`): a site measured as
// refusing is a link card instead, and one not measured is framed with "Open in a new tab" below it, as is every
// other. Nothing autoplays on its
// own; a video obeys her cue (play, pause, seek) while the page is open (`player.ts`).
import { useEffect, useRef } from 'preact/hooks';
import type { BenchPiece } from '../../../api/types';
import { onBenchCue } from '../../../session/live';
import { drivable, driveFile, messageFor, type Cue, type Provider } from './player';
import { showsCard } from './siteCard';

/** The URL as an https URL, or null: the server checks a body, but a page does not trust what it frames. */
function httpsUrl(text: string): URL | null {
  try {
    const url = new URL(text.trim());
    return url.protocol === 'https:' ? url : null;
  } catch {
    return null;
  }
}

function OpenLink({ url }: { url: URL }) {
  return (
    <div class="frame-foot">
      <span class="meta frame-host">{url.hostname}</span>
      <a class="btn sm ghost" href={url.href} target="_blank" rel="noopener noreferrer">Open in a new tab</a>
    </div>
  );
}

// No allow-same-origin: a framed site runs in an opaque origin and cannot reach this page's cookies or storage.
const SITE_SANDBOX = 'allow-scripts allow-forms allow-popups';
// A provider's player needs its own origin; it is still cross-origin to this page, and the hosts are fixed server-side.
const PLAYER_SANDBOX = 'allow-scripts allow-same-origin allow-presentation';

function SiteCard({ url, title }: { url: URL; title: string }) {
  return (
    <div class="site-card">
      {title && <strong class="site-card-title">{title}</strong>}
      <span class="site-card-host">{url.hostname}</span>
      <span class="meta">This site does not allow being shown here.</span>
      <a class="btn sm" href={url.href} target="_blank" rel="noopener noreferrer">Open in a new tab</a>
    </div>
  );
}

export function SiteView({ piece }: { piece: BenchPiece }) {
  const body = piece.body;
  const url = httpsUrl(body);
  if (!url) return <div class="pbody"><span class="unk">not an https address, so not shown: “{body}”</span></div>;
  if (showsCard(piece.site)) return <div class="pbody frame"><SiteCard url={url} title={piece.site?.title ?? ''} /></div>;
  return (
    <div class="pbody frame">
      <iframe class="frame-box site" src={url.href} title={url.hostname} sandbox={SITE_SANDBOX}
        referrerpolicy="no-referrer" loading="lazy" />
      <OpenLink url={url} />
    </div>
  );
}

/** Drives the player in `box` (an iframe, or a `<video>` for a file) with each cue she makes for this piece. An iframe
 *  that has not loaded cannot be told anything, so a cue before then is dropped, as a cue is for who is looking now. */
function useCues(bench: number, piece: number, provider: Provider, origin: string): {
  frame: { current: HTMLIFrameElement | null };
  file: { current: HTMLVideoElement | null };
  loaded: () => void;
} {
  const frame = useRef<HTMLIFrameElement | null>(null);
  const file = useRef<HTMLVideoElement | null>(null);
  const ready = useRef(false);
  useEffect(() => {
    ready.current = false;
    return onBenchCue((b, p, cue: Cue) => {
      if (b !== bench || p !== piece) return;
      if (provider === 'file') {
        if (file.current) driveFile(file.current, cue);
        return;
      }
      const message = messageFor(provider, cue);
      if (ready.current && message !== null) frame.current?.contentWindow?.postMessage(message, origin);
    });
  }, [bench, piece, provider, origin]);
  return { frame, file, loaded: () => { ready.current = true; } };
}

export function VideoView({ bench, piece }: { bench: number; piece: BenchPiece }) {
  const video = piece.video;
  const url = video ? httpsUrl(video.url) : null;
  const embed = video ? httpsUrl(video.embed_url) : null;
  const provider = video?.provider ?? 'file';
  const cues = useCues(bench, piece.id, provider, embed?.origin ?? '');
  if (!video || !url || !embed) return <div class="pbody"><span class="unk">not a video this page can show</span></div>;
  return (
    <div class="pbody frame">
      {video.provider === 'file' ? (
        <video class="frame-box file" controls preload="metadata" playsInline title={piece.title} ref={cues.file}
          src={video.start ? `${embed.href}#t=${video.start}` : embed.href} />
      ) : (
        <iframe class="frame-box player" src={drivable(video.provider, embed).href} title={piece.title} ref={cues.frame}
          onLoad={cues.loaded} sandbox={PLAYER_SANDBOX} referrerpolicy="strict-origin-when-cross-origin"
          allow="fullscreen; picture-in-picture" allowFullScreen loading="lazy" />
      )}
      <OpenLink url={url} />
    </div>
  );
}
