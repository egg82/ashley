# Wake words

`hey_ashley` is a microWakeWord model that wakes on "hey Ashley" and "okay Ashley" and is trained to ignore a bare
"Ashley" and mentions of her ("did you ask Ashley", "tell Ashley"). It runs on the satellite, so no audio leaves the
device until it fires.

It is the only model on the Atom Echo: there, only the first model in `micro_wake_word.models` ever fires (a second
`okay_nabu`, and before that stock `hey_jarvis`, never did), though ESPHome loads and runs the rest without an error.

Trained with `ghcr.io/tatertotterson/microwakeword:v47.3` from TTS clips: 25,000 each of "hey Ashley"
and "okay Ashley" as positives, 8,500 of bare "Ashley" as hard negatives, on upstream's `okay_nabu` architecture
(64 pointwise filters, 32 first-conv filters, stride 3) in place of the trainer's larger default. The training
scripts and corpora are kept outside this repo; the scoring below runs a model over clip folders and over long
recordings the way ESPHome does.

Scored at the cutoff and window in `hey_ashley.json` (0.98, 7) on clips it never trained on:

| Set | Fired |
|---|---|
| "hey Ashley", 100 clips | 100% |
| bare "Ashley", 2,000 clips | 0.1% |
| CHiME household audio, 500 clips | 0 per hour |
| AudioSet general audio, 500 clips | 0 per hour |

Stock `okay_nabu` also scores 0 per hour on the same CHiME and AudioSet clips. On a test Echo it woke on every
"hey Ashley" and "okay Ashley" tried and on no bare "Ashley".
