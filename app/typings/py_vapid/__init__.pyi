"""The part of py-vapid that `ashley.channels.push.sender` uses; the package ships no type information."""

class Vapid01:
    @classmethod
    def from_string(cls, private_key: str) -> "Vapid01": ...
