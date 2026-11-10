"""Shared by the media suites: small real recordings made with ffmpeg once per session, and a fake Wyoming speech
service that answers each window it is sent with a numbered text and counts them."""

import asyncio
import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from wyoming.asr import Transcript
from wyoming.audio import AudioStop
from wyoming.event import async_read_event, async_write_event

SUBTITLES = "1\n00:00:01,000 --> 00:00:02,000\nHello <i>world</i>\n\n2\n00:00:03,500 --> 00:00:04,500\nSecond cue\n"
FFMPEG = ["ffmpeg", "-v", "error", "-y"]
VIDEO = ["-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=10"]
SOUND = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
SILENCE = ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "6"]


def make(path: Path, *inputs: list[str], tail: list[str]) -> Path:
    """Run ffmpeg over the `inputs` (each a list of arguments) to write `path`."""
    subprocess.run([*FFMPEG, *(a for i in inputs for a in i), *tail, str(path)], check=True)
    return path


def recordings(root: Path) -> dict[str, Path]:
    """`talk` (video, sound, embedded subtitles), `plain` (video, sound), `silent` (video, silence), `mute` (video only)
    and `song` (sound only), each 6 seconds."""
    subs = root / "subs.srt"
    subs.write_text(SUBTITLES)
    return {
        "talk": make(root / "talk.mp4", VIDEO, SOUND, ["-i", str(subs)], tail=["-c:v", "mpeg4", "-c:a", "aac", "-c:s", "mov_text"]),
        "plain": make(root / "plain.mp4", VIDEO, SOUND, tail=["-c:v", "mpeg4", "-c:a", "aac"]),
        "silent": make(root / "silent.mp4", VIDEO, SILENCE, tail=["-c:v", "mpeg4", "-c:a", "aac"]),
        "mute": make(root / "mute.mp4", VIDEO, tail=["-c:v", "mpeg4"]),
        "song": make(root / "song.mp3", SOUND, tail=["-c:a", "libmp3lame"]),
    }


class Whisper:
    """A Wyoming speech service on a local port. Each window sent to it (one connection each) is answered
    `window <n>`, n counting from 1; `windows` is how many it has answered."""

    def __init__(self) -> None:
        self.windows = 0
        self.uri = ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while (event := await async_read_event(reader)) is not None:
            if AudioStop.is_type(event.type):
                self.windows += 1
                await async_write_event(Transcript(text=f"window {self.windows}").event(), writer)
                break
        writer.close()


@asynccontextmanager
async def whisper() -> AsyncGenerator[Whisper]:
    fake = Whisper()
    server = await asyncio.start_server(fake.handle, "127.0.0.1", 0)
    fake.uri = f"tcp://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    try:
        yield fake
    finally:
        server.close()
        await server.wait_closed()
