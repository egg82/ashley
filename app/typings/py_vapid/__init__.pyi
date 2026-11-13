"""The part of py-vapid that `ashley.channels.push.sender` uses, and the signing its tests check a key pair with; the
package ships no type information."""

class Vapid01:
    @classmethod
    def from_string(cls, private_key: str) -> "Vapid01": ...
    def sign(self, claims: dict[str, str | int], crypto_key: str | None = None) -> dict[str, str]: ...
