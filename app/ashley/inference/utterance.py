"""An utterance read once from its source and readable again from the start, so a route that fails mid-utterance
hands the next route everything heard so far plus the rest."""

from collections.abc import AsyncIterator

from .speech import Heard


class Utterance:
    def __init__(self, heard: Heard) -> None:
        self.format = heard.format
        self.error: Exception | None = None
        self._source = heard.chunks
        self._seen: list[bytes] = []
        self._size = 0
        self._ended = False

    @property
    def duration_ms(self) -> int:
        return self.format.duration_ms(self._size)

    async def chunks(self) -> AsyncIterator[bytes]:
        """Every chunk from the first, then each new one as it arrives from the source. If the source raised, that
        error is raised again at the point it happened."""
        i = 0
        while True:
            if i < len(self._seen):
                i += 1
                yield self._seen[i - 1]
            elif self.error is not None:
                raise self.error
            elif self._ended:
                return
            else:
                await self._pull()

    async def drain(self) -> None:
        """Read the source to its end, discarding nothing."""
        while self.error is None and not self._ended:
            await self._pull()

    async def _pull(self) -> None:
        try:
            chunk = await anext(self._source)
        except StopAsyncIteration:
            self._ended = True
        except Exception as e:
            self.error = e
        else:
            if chunk:
                self._seen.append(chunk)
                self._size += len(chunk)
