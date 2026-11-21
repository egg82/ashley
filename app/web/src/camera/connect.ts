// Opens one camera feed in a video element: the page makes the WebRTC offer, hands it to her (`api/screenFeed.ts`) and
// plays what the camera sends back, muted. The steps follow Home Assistant's own player: the offer carries the candidates
// gathered while it was made, later ones follow once her stream names the session, and a camera that needs a data channel
// is given one. `failed` is called once when the feed cannot be had: a refusal, an `error` signal, the stream or the
// connection ending or failing, or no media within `CONNECT_MS`.
import type { FeedRoutes } from '../api/screenFeed';
import { signals } from '../api/screenFeed';
import type { ScreenFeed } from '../api/types';

/** How long a feed may take to start playing before it is called failed. */
export const CONNECT_MS = 20_000;

export interface Link {
  close(): void;
}

/** What opening a feed needs of the browser, so it can be driven without one. */
export interface Browser {
  peer(config: RTCConfiguration): RTCPeerConnection;
}

export const browser: Browser = { peer: (config) => new RTCPeerConnection(config) };

function init(candidate: string, mid: string | null, index: number | null, fragment: string | null): RTCIceCandidateInit {
  // A candidate with neither mid nor index is not accepted by a browser: mid 0, as Home Assistant's player does.
  const named = mid !== null || index !== null;
  return { candidate, sdpMid: named ? mid : '0', sdpMLineIndex: index, usernameFragment: fragment };
}

export function connect(routes: FeedRoutes, screen: string, feed: ScreenFeed, video: HTMLVideoElement, failed: () => void,
                        on: Browser = browser): Link {
  const abort = new AbortController();
  const pc = on.peer({ iceServers: feed.ice_servers.map((s) => ({
    urls: s.urls, ...(s.username === null ? {} : { username: s.username }),
    ...(s.credential === null ? {} : { credential: s.credential }) })) });
  let session: string | null = null;
  let queued: RTCIceCandidate[] = [];
  let ended = false;
  const timer = setTimeout(fail, CONNECT_MS);

  function fail(): void {
    if (ended) return;
    close();
    failed();
  }

  function close(): void {
    ended = true;
    clearTimeout(timer);
    abort.abort();
    pc.close();
  }

  function send(candidate: RTCIceCandidate, id: string): void {
    void routes.candidate(screen, id, candidate.toJSON()).catch(() => undefined);
  }

  pc.onicecandidate = (e) => {
    if (!e.candidate?.candidate) return;
    if (session === null) queued.push(e.candidate);
    else send(e.candidate, session);
  };
  pc.ontrack = (e) => {
    video.muted = true;
    video.srcObject = e.streams[0] ?? new MediaStream([e.track]);
    void video.play().catch(() => undefined);
    clearTimeout(timer);
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === 'failed' || pc.connectionState === 'closed') fail();
  };
  if (feed.data_channel) pc.createDataChannel(feed.data_channel);
  pc.addTransceiver('video', { direction: 'recvonly' });
  pc.addTransceiver('audio', { direction: 'recvonly' });
  void negotiate().catch(fail);

  async function negotiate(): Promise<void> {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const gathered = queued.map((c) => `a=${c.candidate}\r\n`).join('');
    queued = [];
    const stream = await routes.offer(screen, (offer.sdp ?? '') + gathered, abort.signal);
    for await (const signal of signals(stream)) {
      if (ended) return;
      if (signal.type === 'session') {
        session = signal.session_id;
        queued.forEach((c) => send(c, signal.session_id));
        queued = [];
      } else if (signal.type === 'answer') await pc.setRemoteDescription({ type: 'answer', sdp: signal.answer });
      else if (signal.type === 'candidate')
        await pc.addIceCandidate(init(signal.candidate, signal.sdp_mid, signal.sdp_m_line_index, signal.username_fragment))
          .catch(() => undefined);
      else throw new Error('the camera did not answer');
    }
    if (!ended) throw new Error('the stream ended');
  }

  return { close: () => { if (!ended) close(); } };
}
