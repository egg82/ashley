"""A stored clip turned into her voice, for the clip route to stream."""

from ... import services
from ...inference.inference import Inference, InferenceUnavailable
from ...inference.speech import Speech
from .clips import Clip, Clips, ClipsUnavailable


class PlaybackUnavailable(Exception):
    """The clip could not be read, or no speech route started. Transient."""


async def speech_for(token: str) -> tuple[Clip, Speech] | None:
    """The clip `token` names and `Inference.speak` of its text, started; None when the token names no clip or an
    expired one. Raises PlaybackUnavailable."""
    try:
        clip = await services.get(Clips).get(token)
        if clip is None:
            return None
        return clip, await services.get(Inference).speak("speak", clip.body)
    except (ClipsUnavailable, InferenceUnavailable) as e:
        raise PlaybackUnavailable() from e
