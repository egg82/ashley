"""A Printables model's page as the text `read_page` returns: the model's name, author, counts, license, category and
publish date, the files it offers (name and size, no ids) and the description its author wrote, as plain text. Pure;
`pages` asks the service."""

from ..printables.model import Detail
from . import page_fetch, page_text


def page_of(detail: Detail) -> page_fetch.Page:
    """`detail` as a page titled by the model's name."""
    model = detail.model
    lines = [f"Title: {model.name}"]
    for label, value in (("Author", model.author), ("Category", detail.category), ("License", detail.license),
                         ("Published", detail.published)):
        if value:
            lines.append(f"{label}: {value}")
    rating = "" if model.rating is None else f", rated {model.rating} of 5"
    lines.append(f"{model.likes} likes, {model.downloads} downloads, {model.makes} makes{rating}")
    if model.files:
        lines.append("Files:")
        lines += [f"- {f.name} ({f.size} bytes)" for f in model.files]
    description = page_text.text_of(detail.description)
    if description:
        lines.append(f"Description:\n{description}")
    text = "\n".join(lines)
    return page_fetch.Page(text, len(text.encode()), model.name)
