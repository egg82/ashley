"""The prompt-sizes eval's table and JSON: section, source and tool names, characters and tokens, never the text."""

import json
from dataclasses import asdict, dataclass

from .prompt_sizes import Part, Sizes


@dataclass(frozen=True)
class Meta:
    """What was measured: the conversation `kind` and `channel`, the route counted (`provider`, `model`), the route
    the turn tries first when that is not the one counted (`first`, `provider/model`, else empty) and the characters
    of the ask the turn recalled for."""

    kind: str
    channel: str
    provider: str
    model: str
    first: str
    ask_chars: int


def _row(label: str, part: Part, indent: int = 2) -> str:
    return f"{' ' * indent}{label:<44} {part.chars:>8} {part.tokens:>8}"


def render(sizes: Sizes, meta: Meta) -> str:
    """The table: stable sections, the moment layer, each source's tools and each tool by tokens, the reply schema and
    the whole request."""
    note = f" (first route {meta.first})" if meta.first else ""
    lines = [f"prompt sizes: kind={meta.kind} channel={meta.channel} counted on {meta.provider}/{meta.model}{note}",
             f"{'part':<46} {'chars':>8} {'tokens':>8}", "stable"]
    lines += [_row(p.name, p) for p in sizes.stable]
    lines += [f"  {'(blank lines between sections)':<44} {sizes.joins:>8} {'':>8}", _row("stable, counted whole", sizes.stable_whole),
              "moment", _row("moment", sizes.moment), f"tools ({len(sizes.tools)})"]
    lines += [_row(f"{g.name} ({g.members} tools)", g) for g in sizes.groups]
    lines += [_row("all tools, counted whole", sizes.tools_whole), "tools by tokens"]
    lines += [_row(t.name, t) for t in sorted(sizes.tools, key=lambda t: -t.tokens)]
    lines += ["reply schema", _row("reply schema", sizes.reply_schema),
              f"request counted whole: {sizes.whole} tokens, over a baseline of {sizes.baseline}; {sizes.calls} counts"]
    return "\n".join(lines)


def to_json(sizes: Sizes, meta: Meta) -> str:
    """Every part as `{name, chars, tokens, members}` under its layer, with the baselines and the whole request."""
    return json.dumps({"meta": asdict(meta), "model": sizes.model, "baseline": sizes.baseline,
                       "stable_fixed": sizes.stable_fixed, "tools_fixed": sizes.tools_fixed,
                       "stable": {"sections": [asdict(p) for p in sizes.stable], "joins_chars": sizes.joins,
                                  "whole": asdict(sizes.stable_whole)},
                       "moment": asdict(sizes.moment),
                       "tools": {"whole": asdict(sizes.tools_whole), "groups": [asdict(g) for g in sizes.groups],
                                 "items": [asdict(t) for t in sizes.tools]},
                       "reply_schema": asdict(sizes.reply_schema), "whole_request_tokens": sizes.whole,
                       "calls": sizes.calls}, indent=2)
