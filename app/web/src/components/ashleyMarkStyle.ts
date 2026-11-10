// Motion for AshleyMark, keyed on the svg's data-state. Transforms pivot on the user-space origin, the mark's centre.
export const ASHLEY_MARK_CSS = `
.am-wire{fill:none;stroke:#B98A4E;stroke-width:.7;opacity:.55}
.am-back{fill:none;stroke-linecap:round;opacity:.4}
.am-front{fill:none;stroke-linecap:round}
.am-a{stroke:#F2B45A;stroke-width:2.6}
.am-b{stroke:#D9785A;stroke-width:1.8}
.am-spark{fill:#FFF1D6}
.am-ripple{fill:none;stroke:#FFD58A;stroke-width:.35;opacity:0}
.am-tilt-a{transform:rotate(-16deg)}
.am-tilt-b{transform:rotate(52deg)}
.am-globe{transform:rotate(-16deg)}
.am-m1{transform:scaleX(.38)}
.am-m2{transform:scaleX(.82)}
.am-sa{offset-path:path('M38 0A38 11.5 0 1 1 -38 0A38 11.5 0 1 1 38 0');offset-rotate:0deg;offset-distance:18%}
.am-sb{offset-path:path('M33 0A33 8 0 1 1 -33 0A33 8 0 1 1 33 0');offset-rotate:0deg;offset-distance:60%;opacity:0}
.am-eye{transform-box:fill-box;transform-origin:50% 50%}
.am-eyes{transform-box:fill-box;transform-origin:center;transition:transform .3s}
[data-state="listening"] .am-eyes{transform:scale(1.15)}
svg[data-state="unreachable"]{filter:grayscale(1) brightness(.5)}
[data-state="unreachable"] *{animation:none!important}

@media (prefers-reduced-motion: no-preference){
  .am-tilt-a{animation:am-rock-a 9s ease-in-out infinite alternate}
  .am-tilt-b{animation:am-rock-b 11s ease-in-out infinite alternate}
  .am-m1{animation:am-turn 12s ease-in-out infinite alternate}
  .am-m2{animation:am-turn 12s ease-in-out -6s infinite alternate}
  .am-sa{animation:am-orbit 16s cubic-bezier(.6,0,.4,1) infinite}
  .am-core{animation:am-breathe 5.5s ease-in-out infinite}
  .am-eye{animation:am-blink 6.4s infinite}

  [data-state="listening"] .am-tilt-a,
  [data-state="listening"] .am-globe{animation:am-level .7s cubic-bezier(.2,.8,.2,1) forwards}
  [data-state="listening"] .am-tilt-b{animation:am-level-b .7s cubic-bezier(.2,.8,.2,1) forwards}
  [data-state="listening"] .am-m1,
  [data-state="listening"] .am-m2,
  [data-state="listening"] .am-sa{animation-play-state:paused}
  [data-state="listening"] .am-core{animation:am-attend 2.4s ease-in-out infinite}
  [data-state="listening"] .am-ripple{animation:am-inward 2.4s ease-in infinite}
  [data-state="listening"] .am-r2{animation-delay:-1.2s}

  [data-state="thinking"] .am-tilt-a{animation:am-spin 3s linear infinite}
  [data-state="thinking"] .am-tilt-b{animation:am-spin-r 4.5s linear infinite}
  [data-state="thinking"] .am-m1{animation:am-turn 1.6s ease-in-out infinite alternate}
  [data-state="thinking"] .am-m2{animation:am-turn 1.6s ease-in-out -.8s infinite alternate}
  [data-state="thinking"] .am-sa{animation:am-orbit 1.4s linear infinite}
  [data-state="thinking"] .am-sb{opacity:1;animation:am-orbit 1.9s linear infinite reverse}
  [data-state="thinking"] .am-core{animation:am-breathe 1.1s ease-in-out infinite}
  [data-state="thinking"] .am-eyes{animation:am-glance 3.2s ease-in-out infinite}

  [data-state="speaking"] .am-core{animation:am-syllable 1.9s linear infinite}
  [data-state="speaking"] .am-front{animation:am-flare 1.9s linear infinite}
  [data-state="speaking"] .am-ripple{animation:am-outward 1.9s ease-out infinite}
  [data-state="speaking"] .am-r2{animation-delay:-.95s}
}

@keyframes am-rock-a{from{transform:rotate(-21deg)}to{transform:rotate(-11deg)}}
@keyframes am-rock-b{from{transform:rotate(46deg)}to{transform:rotate(58deg)}}
@keyframes am-level{to{transform:rotate(0deg)}}
@keyframes am-level-b{to{transform:rotate(90deg)}}
@keyframes am-spin{from{transform:rotate(-16deg)}to{transform:rotate(344deg)}}
@keyframes am-spin-r{from{transform:rotate(52deg)}to{transform:rotate(-308deg)}}
@keyframes am-turn{from{transform:scaleX(1)}to{transform:scaleX(-1)}}
@keyframes am-orbit{from{offset-distance:0%}to{offset-distance:100%}}
@keyframes am-breathe{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}
@keyframes am-attend{0%,100%{transform:scale(1.05)}50%{transform:scale(.95)}}
@keyframes am-inward{0%{transform:scale(2.4);opacity:0}40%{opacity:.6}100%{transform:scale(1);opacity:0}}
@keyframes am-outward{0%{transform:scale(1);opacity:.7}100%{transform:scale(2.4);opacity:0}}
@keyframes am-syllable{
  0%{transform:scale(1)}8%{transform:scale(1.22)}16%{transform:scale(1.02)}
  24%{transform:scale(1.15)}34%{transform:scale(1)}46%{transform:scale(1.26)}
  58%{transform:scale(1.04)}66%{transform:scale(1.12)}78%{transform:scale(1)}100%{transform:scale(1)}}
@keyframes am-flare{0%,34%,78%,100%{opacity:.85}8%,46%{opacity:1}}
@keyframes am-blink{0%,94%,100%{transform:scaleY(1)}96%{transform:scaleY(.1)}}
@keyframes am-glance{0%,100%{transform:translate(0,0)}30%{transform:translate(-2.5px,-1.5px)}60%{transform:translate(2.5px,-1.5px)}}
`;
