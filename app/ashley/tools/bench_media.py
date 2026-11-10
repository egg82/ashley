"""Her eyes and ears on a recording on a bench, for one turn of its talk (`channels.turn_tools`), offered while an object
store and a media worker (`ashley.runs.media.Media`) are wired:

- `bench_frames` shows a video (`clip`) piece at the moments she picks, one picture in the result, kept with the turn
  like a look (`bench_picture`), so the page shows what she saw and the turn's looks are counted together.
- `bench_transcribe` makes a reader piece of what is said in a `clip` or `audio` piece, or a YouTube `video` piece, timestamped, beside it:
  from the captions of a file piece she names, else (a YouTube video) its English captions fetched by the media worker,
  else from the captions inside the recording, else by the speech service.

Neither changes the recording. Logs: `tools.call` with the bench, piece, counts and `source`; the worker logs its own."""

import math
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .. import services
from ..files import config as files_config
from ..files.store import NullStore, ObjectStore, StoreUnavailable
from ..inference.model import Image, ToolCall, ToolResult, ToolSpec
from ..looks import config as looks_config
from ..looks.looks import LooksUnavailable
from ..runs import media_config
from ..runs.captions import Segment, lines_of, parse_captions, spoken
from ..runs.media import Media, MediaUnavailable, Source
from ..workshop import embed, reader, stored_file
from ..workshop import rules as workshop_rules
from ..workshop.commands import Add, Move
from ..workshop.model import HER, Owner, Piece, Place, Text
from ..workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_picture, bench_results
from .bench_args import BadArguments, check_names, piece_id_of
from .bench_file_text import text_of
from .tools import Catalogue, Tools

FRAMES = "bench_frames"
TRANSCRIBE = "bench_transcribe"
RULES = workshop_rules.load()
LOOKS = looks_config.load()
MEDIA = media_config.load()
FILES = files_config.load()
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?")
LAYOUT = "left to right, then down, three across"
FRAMES_SPEC = ToolSpec(
    FRAMES, "Look at a video (clip) piece at the moments you pick: `at` is up to "
    f"{MEDIA.max_frames} times in seconds from the start. The frames come back to you as one picture in this result, in "
    f"the order you gave ({LAYOUT}), and are kept with this message so the person sees what you saw. A moment past the "
    "end is the last frame.",
    {"type": "object", "properties": {"piece_id": {"type": "integer"},
                                      "at": {"type": "array", "items": {"type": "number"}}},
     "required": ["piece_id", "at"]}, reads=True, outside=True)
TRANSCRIBE_SPEC = ToolSpec(
    TRANSCRIBE, "Put the words of a video (clip), audio or YouTube video piece on the bench as a reader piece beside it, "
    "each line stamped with the time it starts. A YouTube video's English captions are fetched for you, and a video without any needs `captions_piece`. "
    "If the person put the captions on the bench as a file piece (.srt or .vtt), give its id as `captions_piece`; "
    "otherwise the captions inside the file are used, and with none the speech is transcribed in windows of a few "
    "seconds, which takes a while. `language` (a code such as `en`) is optional. Read the result with bench_read_piece; to take the person to a moment, use bench_cue with the stamped time.",
    {"type": "object", "properties": {"piece_id": {"type": "integer"}, "captions_piece": {"type": "integer"},
                                      "language": {"type": "string"}}, "required": ["piece_id"]}, outside=True, tier="judged")
INSTRUCTIONS = ("For a video piece, bench_transcribe gives you what is said (captions first, else speech) and bench_frames "
                "shows it at moments you pick; for an audio piece only the transcript. Transcribe once, then read the "
                "reader piece it made; take frames at the moments the words or the person point to, not at random.")
CANNOT = {"no_video": "that recording has no picture", "no_audio": "that recording has no sound",
          "too_long": f"that recording is longer than the {MEDIA.max_audio_s // 60} minutes of sound this takes",
          "no_speech_service": "there is no speech service to listen with, and the file has no captions",
          "speech_down": "the speech service could not be reached; try again shortly",
          "no_captions": "that YouTube video has no English captions, manual or automatic: ask the person to put captions "
                         "for it on the bench as a file piece (.srt or .vtt) and give it as captions_piece",
          "unreadable": "that file could not be read as a recording", "wrong_file": "the stored file is not the one named",
          "no_frame": "no frame could be taken there", "too_large": "the picture came out too large to give you"}


class Cannot(Exception):
    """A call that cannot be done, for `outcome`; `reason` is what she is told."""

    def __init__(self, outcome: str, reason: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.reason = reason


class BenchMediaTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, conversation_id: int, turn_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._said = (conversation_id, turn_id)

    async def catalogue(self) -> Catalogue:
        """Empty unless an object store and a media worker are wired."""
        if isinstance(services.get(ObjectStore), NullStore) or not services.get(Media).available():
            return Catalogue((), None)
        return Catalogue((FRAMES_SPEC, TRANSCRIBE_SPEC), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the worker or the model did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        spec = {FRAMES: FRAMES_SPEC, TRANSCRIBE: TRANSCRIBE_SPEC}.get(call.name)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            piece_id = piece_id_of(call.arguments)
            if call.name == FRAMES:
                return await self._frames(call, started, piece_id)
            return await self._transcribe(call, started, piece_id)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except Cannot as e:
            return bench_results.failed(call, started, e.outcome, e.reason, bench=self._bench)
        except MediaUnavailable as e:
            return bench_results.failed(call, started, "unavailable", CANNOT.get(e.reason, f"the recording could not "
                                        f"be worked on ({e.reason})"), bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable, LooksUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench or its storage cannot be reached "
                                        "right now; nothing was done", bench=self._bench)

    async def _frames(self, call: ToolCall, started: float, piece_id: int) -> ToolResult:
        at = moments_of(call.arguments)
        view = await services.get(Workshop).read(self._owner, self._bench)
        piece, source = recording(view.pieces, piece_id, ("clip",))
        over = await bench_picture.over_limit(self._owner.household_id, self._said[1], call.id, LOOKS.max_looks_per_turn)
        if over is not None:
            raise Cannot("limit", over)
        sheet = await services.get(Media).frames(f"media-{uuid.uuid4().hex[:12]}", self._source(source), at)
        picture = Image("image/jpeg", sheet.jpeg)
        await bench_picture.keep(self._owner.household_id, self._said, call.id, self._bench, piece.id, picture)
        body: dict[str, object] = {"of": f"piece {piece.id}", "frames": sheet.count, "at": list(at), "layout": LAYOUT,
                                   "duration_s": round(sheet.duration_s, 1), "picture": "follows in this result"}
        done = bench_results.ok(call, started, body, bench=self._bench, piece=piece.id, frames=sheet.count,
                                bytes=len(sheet.jpeg))
        return replace(done, images=(picture,))

    async def _transcribe(self, call: ToolCall, started: float, piece_id: int) -> ToolResult:
        view = await services.get(Workshop).read(self._owner, self._bench)
        language = language_of(call.arguments)
        piece, found, how, seconds = await self._words_of(view.pieces, piece_id, call.arguments, language)
        heard = spoken(list(found))
        if not heard:
            raise Cannot("nothing_said", "nothing was heard in it, so there is no transcript to put up")
        title = f"Transcript of {piece.text.title}"[:RULES.title_max_chars].strip()
        body = reader.body_of("", title, lines_of(heard), reader.Recording(piece.id, tuple(round(s.start, 3) for s in heard)))
        added = await services.get(Workshop).apply(self._owner, self._bench, Add(HER, "reader", Text(title, body), "medium"))
        if added.outcome != "accepted":
            return bench_results.failed(call, started, added.outcome, bench_results.HINTS[added.outcome],
                                        bench=self._bench, command="add", seq=added.seq)
        assert added.piece_id is not None
        beside = Place(piece.place.order + 1, "medium")
        await services.get(Workshop).apply(self._owner, self._bench, Move(HER, added.piece_id, beside))
        result: dict[str, object] = {"piece_id": added.piece_id, "source": how, "segments": len(found), "seconds": seconds}
        return bench_results.ok(call, started, result, bench=self._bench, command="add", seq=added.seq, piece=piece.id,
                                source=how, segments=len(found))

    async def _words_of(self, pieces: tuple[Piece, ...], piece_id: int, args: Mapping[str, object],
                        language: str | None) -> tuple[Piece, tuple[Segment, ...], str, int]:
        """The piece and what is said in it, where that came from and the seconds of sound heard. Raises Cannot."""
        online = online_video(pieces, piece_id)
        piece, source = (online, None) if online is not None else recording(pieces, piece_id, ("clip", "audio"))
        sidecar = await self._sidecar(pieces, args)
        if sidecar is not None:
            return piece, tuple(sidecar), "captions", 0
        if source is None:
            words, how, seconds = await youtube_words(piece)
            return piece, words, how, seconds
        said = await services.get(Media).transcribe(f"media-{uuid.uuid4().hex[:12]}", self._source(source), language)
        return piece, said.segments, said.source, int(said.duration_s)

    async def _sidecar(self, pieces: tuple[Piece, ...], args: Mapping[str, object]) -> list[Segment] | None:
        """The cues of the captions file piece the call names, None when it names none."""
        wanted = args.get("captions_piece")
        if wanted is None:
            return None
        if type(wanted) is not int:
            raise BadArguments("captions_piece is a whole number")
        found = next((p for p in pieces if p.id == wanted), None)
        text = None if found is None else await text_of(self._owner.household_id, found, FILES)
        if text is None:
            raise Cannot("no_captions", "captions_piece is not a text file piece (.srt or .vtt) on the bench's layout")
        cues = parse_captions(text)
        if not cues:
            raise Cannot("no_captions", "no timed cues were found in that file; it is not SubRip or WebVTT")
        return cues

    def _source(self, file: stored_file.StoredFile) -> Source:
        return Source(self._owner.household_id, file.sha256, file.size, file.media_type)


def recording(pieces: tuple[Piece, ...], piece_id: int, kinds: tuple[str, ...]) -> tuple[Piece, stored_file.StoredFile]:
    """The piece `piece_id` of one of `kinds` and the file it names. Raises Cannot."""
    piece = next((p for p in pieces if p.id == piece_id), None)
    if piece is None:
        raise Cannot("no_such_piece", "no piece with that id is on the bench's layout; bench_read lists them")
    file = stored_file.file_of(piece.text.body) if piece.kind in kinds else None
    if file is None:
        raise Cannot("not_a_recording", "that piece is not " + " or ".join(f"a {k} piece" for k in kinds))
    return piece, file


def online_video(pieces: tuple[Piece, ...], piece_id: int) -> Piece | None:
    """The video piece `piece_id` when it shows a YouTube video; None when it is not a video piece of one."""
    piece = next((p for p in pieces if p.id == piece_id and p.kind == "video"), None)
    video = None if piece is None else embed.video_of(piece.text.body)
    return piece if video is not None and video.provider == "youtube" else None


async def youtube_words(piece: Piece) -> tuple[tuple[Segment, ...], str, int]:
    """The English captions of the YouTube video `piece` shows, where they came from and the seconds the video runs.
    Raises Cannot `no_english_captions` for a video with no English track, MediaUnavailable for any other failure."""
    video = embed.video_of(piece.text.body)
    video_id = None if video is None else embed.youtube_id_of(video.url)
    if video_id is None:
        raise Cannot("not_a_recording", "that video piece holds no YouTube address to take captions from")
    try:
        said = await services.get(Media).youtube_captions(f"media-{uuid.uuid4().hex[:12]}", video_id)
    except MediaUnavailable as e:
        if e.reason == "no_captions":
            raise Cannot("no_english_captions", CANNOT["no_captions"]) from e
        raise
    return said.segments, said.source, int(said.duration_s)


def moments_of(args: Mapping[str, object]) -> tuple[float, ...]:
    """The `at` argument: 1 to `max_frames` finite times of 0 seconds or more. Raises BadArguments."""
    raw = args.get("at")
    loose: Any = raw
    if not isinstance(raw, list):
        raise BadArguments(f"at is a list of 1 to {MEDIA.max_frames} times in seconds")
    times = list[object](loose)
    if not 1 <= len(times) <= MEDIA.max_frames:
        raise BadArguments(f"at is a list of 1 to {MEDIA.max_frames} times in seconds")
    return tuple(_seconds(t) for t in times)


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(str(value))) or float(str(value)) < 0:
        raise BadArguments("each time in at is a number of seconds, 0 or more")
    return float(str(value))


def language_of(args: Mapping[str, object]) -> str | None:
    """The `language` argument, a short code, or None when it is not given. Raises BadArguments."""
    raw = args.get("language")
    if raw is None:
        return None
    if not isinstance(raw, str) or not LANGUAGE.fullmatch(raw):
        raise BadArguments("language is a short code such as en or pt-BR")
    return raw
