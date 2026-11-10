import { useId } from 'preact/hooks';
import { ASHLEY_MARK_CSS } from './ashleyMarkStyle';

export type MarkState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'unreachable';

/** Ashley's animated mark: a brass gyroscope around a lamp with eyes. `state` sets its motion; `unreachable` is grey and still. */
export function AshleyMark({ state = 'idle', size = 96 }: { state?: MarkState; size?: number }) {
  const id = useId();
  const url = (name: string) => `url(#${id}-${name})`;
  return (
    <svg viewBox="-50 -50 100 100" width={size} height={size} data-state={state} role="img" aria-label="Ashley">
      <defs>
        <radialGradient id={`${id}-halo`} r="0.5">
          <stop offset="0" stop-color="#F2B45A" stop-opacity=".30" />
          <stop offset=".55" stop-color="#C46A4A" stop-opacity=".08" />
          <stop offset="1" stop-color="#C46A4A" stop-opacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-core`} r="0.5">
          <stop offset="0" stop-color="#FFF6E4" />
          <stop offset=".45" stop-color="#FFD58A" />
          <stop offset="1" stop-color="#E8962F" />
        </radialGradient>
        <radialGradient id={`${id}-glow`} r="0.5">
          <stop offset="0" stop-color="#FFD58A" stop-opacity=".75" />
          <stop offset="1" stop-color="#F2B45A" stop-opacity="0" />
        </radialGradient>
        <filter id={`${id}-soft`} x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="1.1" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <style>{ASHLEY_MARK_CSS}</style>
      <circle r="46" fill={url('halo')} />
      <g class="am-tilt-b"><path class="am-back am-b" d="M-33 0A33 8 0 0 1 33 0" /></g>
      <g class="am-tilt-a"><path class="am-back am-a" d="M-38 0A38 11.5 0 0 1 38 0" /></g>
      <g class="am-globe">
        <circle class="am-wire" r="27" />
        <ellipse class="am-wire" rx="27" ry="7" />
        <ellipse class="am-wire" cy="-14" rx="23" ry="5.5" />
        <ellipse class="am-wire" cy="14" rx="23" ry="5.5" />
        <ellipse class="am-wire am-m1" rx="27" ry="27" />
        <ellipse class="am-wire am-m2" rx="27" ry="27" />
      </g>
      <g class="am-core">
        <circle r="24" fill={url('glow')} />
        <circle r="15" fill={url('core')} />
        <g class="am-eyes" fill="#3a1e08">
          <rect class="am-eye" x="-6.2" y="-5.5" width="4" height="9" rx="2" />
          <rect class="am-eye" x="2.2" y="-5.5" width="4" height="9" rx="2" />
        </g>
      </g>
      <circle class="am-ripple" r="16" />
      <circle class="am-ripple am-r2" r="16" />
      <g class="am-tilt-b">
        <path class="am-front am-b" d="M33 0A33 8 0 0 1 -33 0" />
        <circle class="am-spark am-sb" r="1.6" />
      </g>
      <g class="am-tilt-a" filter={url('soft')}>
        <path class="am-front am-a" d="M38 0A38 11.5 0 0 1 -38 0" />
        <circle class="am-spark am-sa" r="2.3" />
      </g>
    </svg>
  );
}
