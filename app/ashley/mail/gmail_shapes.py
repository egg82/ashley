"""Gmail's JSON as the API reference gives it (https://developers.google.com/workspace/gmail/api/reference/rest/v1/):
`users.getProfile`, `users.labels.list`, `users.messages.list`, `users.messages.get`, `users.messages.send`,
`users.messages.batchModify` and `users.drafts.create`. Only the fields read are named; the rest are ignored."""

from pydantic import BaseModel, ConfigDict


class Shape(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Profile(Shape):
    emailAddress: str


class LabelShape(Shape):
    id: str
    name: str
    type: str = "user"


class LabelList(Shape):
    labels: list[LabelShape] = []


class MessageRef(Shape):
    id: str


class MessageList(Shape):
    messages: list[MessageRef] = []
    nextPageToken: str = ""


class HeaderShape(Shape):
    name: str
    value: str


class Body(Shape):
    size: int = 0
    data: str = ""
    attachmentId: str = ""


class Part(Shape):
    mimeType: str = ""
    filename: str = ""
    headers: list[HeaderShape] = []
    body: Body = Body()
    parts: list["Part"] = []


class MessageShape(Shape):
    id: str
    threadId: str = ""
    labelIds: list[str] = []
    snippet: str = ""
    internalDate: str = "0"
    payload: Part = Part()


class DraftShape(Shape):
    id: str


class Empty(Shape):
    pass
