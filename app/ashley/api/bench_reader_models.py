"""Wire models for a reader piece's page (`BenchPiece.reader`) and its highlight (`BenchPiece.pointer`)."""

from pydantic import BaseModel, Field


class PieceRecording(BaseModel):
    """What a transcript was made from: the bench piece `piece_id` (a clip or audio piece) and the second each of the
    reader's paragraphs starts at (`starts[i]` for `paragraphs[i]`)."""

    piece_id: int
    starts: list[float]


class PieceReader(BaseModel):
    """A reader piece's page, understood: where it came from (`url`, https), its own `title` (may be empty), and its
    `paragraphs` in order, which are what a passage's `paragraph` indexes. `recording` is set on a transcript."""

    url: str
    title: str
    paragraphs: list[str]
    recording: PieceRecording | None


class PiecePointer(BaseModel):
    """The passage of a reader piece she highlighted: characters `start` up to `end` (Unicode code points) of paragraph
    `paragraph`. `seq` is the command that put it up, so a screen can tell a highlight it has already brought into
    view from a new one. Null when there is none, or the piece has changed since it was put up."""

    seq: int
    paragraph: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
