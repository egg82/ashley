"""Bridge's gRPC frontend as `keeper_link.BridgeLink` (`bridge --grpc`, which runs with no GUI attached). The stubs are
generated from `bridge.proto`, a copy of Bridge 3.27.1's `internal/frontend/grpc/bridge.proto`, when the image is built, so
this module reads them by name and the keeper's other modules never see them. Bridge writes `grpcServerConfig.json` into its
config directory when it is up: the port or file socket to dial (over TLS under the certificate it lists, whose name does not
match, so the target name is overridden) and the token every call carries as `server-token` metadata. Bridge base64-decodes
the secret of each login call (password, code, mailbox password) and refuses one that does not decode as a wrong password,
so the keeper sends each standard-base64 encoded."""

import base64
import json
import queue
import threading
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

from keeper_link import BridgeError, LoginEvent, Reason, UserEvent, UserInfo, UserState
from keeper_log import emit

CALL_S = 30.0
LOGIN_S = 25.0
_STATES: dict[int, UserState] = {0: "signed_out", 1: "locked", 2: "connected"}
_REASONS: dict[int, Reason] = {0: "credentials", 1: "paid_plan", 2: "connection", 3: "code", 4: "aborted",
                               5: "mailbox_password", 6: "aborted", 7: "verification", 8: "security_key",
                               9: "security_key", 10: "security_key"}
_ASKS: dict[str, LoginEvent] = {"tfaRequested": LoginEvent("tfa"), "tfaOrFidoRequested": LoginEvent("tfa"),
                                "twoPasswordRequested": LoginEvent("two_passwords")}
_SECURITY_KEY_ONLY = ("fidoRequested", "loginFidoTouchRequested", "loginFidoTouchCompleted", "loginFidoPinRequired")


class GrpcBridge:
    def __init__(self, config_dir: Path) -> None:
        """Connect to the Bridge whose `grpcServerConfig.json` is in `config_dir`."""
        self._pb: Any = import_module("bridge_pb2")
        self._empty: Any = import_module("google.protobuf.empty_pb2").Empty()
        self._wrappers: Any = import_module("google.protobuf.wrappers_pb2")
        grpc: Any = import_module("grpc")
        cfg = json.loads((config_dir / "grpcServerConfig.json").read_text())
        self._meta = (("server-token", cfg["token"]),)
        self._channel = _channel(grpc, cfg)
        self._stub: Any = import_module("bridge_pb2_grpc").BridgeStub(self._channel)
        self._login_events: queue.Queue[LoginEvent] = queue.Queue()
        self._on_event: Callable[[UserEvent], None] | None = None
        self._closed = threading.Event()

    def watch(self, on_event: Callable[[UserEvent], None]) -> None:
        self._on_event = on_event
        threading.Thread(target=self._stream, name="bridge-events", daemon=True).start()
        self._call("GuiReady", self._empty)

    def login(self, username: str, password: str, verified: bool = False) -> LoginEvent:
        return self._login("Login", username, password, verified)

    def second_factor(self, username: str, code: str) -> LoginEvent:
        return self._login("Login2FA", username, code)

    def mailbox_password(self, username: str, password: str) -> LoginEvent:
        return self._login("Login2Passwords", username, password)

    def abort(self, username: str) -> None:
        self._call("LoginAbort", self._pb.LoginAbortRequest(username=username))

    def users(self) -> list[UserInfo]:
        return [_user(u) for u in self._call("GetUserList", self._empty).users]

    def user(self, user_id: str) -> UserInfo:
        return _user(self._call("GetUser", self._wrappers.StringValue(value=user_id)))

    def set_split(self, user_id: str, active: bool) -> None:
        self._call("SetUserSplitMode", self._pb.UserSplitModeRequest(userID=user_id, active=active))

    def remove(self, user_id: str) -> None:
        self._call("RemoveUser", self._wrappers.StringValue(value=user_id))

    def export_certificate(self, directory: str) -> None:
        self._call("ExportTLSCertificates", self._wrappers.StringValue(value=directory))

    def close(self) -> None:
        self._closed.set()
        self._channel.close()

    def _call(self, name: str, request: Any) -> Any:
        try:
            return getattr(self._stub, name)(request, metadata=self._meta, timeout=CALL_S)
        except Exception as e:
            raise BridgeError(f"{name}: {type(e).__name__}") from e

    def _login(self, name: str, username: str, secret: str, verified: bool = False) -> LoginEvent:
        while not self._login_events.empty():
            self._login_events.get_nowait()
        fields: dict[str, Any] = {"useHvDetails": True} if verified else {}
        self._call(name, self._pb.LoginRequest(username=username, password=base64.b64encode(secret.encode()), **fields))
        try:
            return self._login_events.get(timeout=LOGIN_S)
        except queue.Empty as e:
            raise BridgeError(f"{name}: no answer") from e

    def _stream(self) -> None:
        request = self._pb.EventStreamRequest(ClientPlatform="keeper")
        try:
            for event in self._stub.RunEventStream(request, metadata=self._meta):
                self._dispatch(event)
        except Exception:
            if not self._closed.is_set():
                raise

    def _dispatch(self, event: Any) -> None:
        which = event.WhichOneof("event")
        if which == "login":
            self._login_event(event.login)
        elif which == "user" and self._on_event is not None:
            for found in self._user_events(event.user):
                self._on_event(found)

    def _login_event(self, login: Any) -> None:
        """Every login event Bridge sends is answered by name here: a person's next step, a refusal with its own reason,
        or (for a oneof member this keeper does not know) `other`, logged. A security key cannot be touched from the
        pod, so any key-only step is a refusal."""
        which = login.WhichOneof("event")
        if which == "error":
            emit("proton_bridge.login_refused", error_type=login.error.type)
            reason = _REASONS.get(login.error.type, "other")
            self._login_events.put(LoginEvent("error", reason=reason))
        elif which == "hvRequested":
            emit("proton_bridge.login_hv")
            self._login_events.put(LoginEvent("human_verification", url=login.hvRequested.hvUrl))
        elif which in ("finished", "alreadyLoggedIn"):
            emit("proton_bridge.login_event", which=which)
            self._login_events.put(LoginEvent("finished", user_id=getattr(login, which).userID))
        elif which in _ASKS:
            emit("proton_bridge.login_event", which=which)
            self._login_events.put(_ASKS[which])
        elif which in _SECURITY_KEY_ONLY:
            emit("proton_bridge.login_event", which=which)
            self._login_events.put(LoginEvent("error", reason="security_key"))
        else:
            emit("proton_bridge.login_event_unhandled", which=which)
            self._login_events.put(LoginEvent("error", reason="other"))

    def _user_events(self, user: Any) -> list[UserEvent]:
        which = user.WhichOneof("event")
        if which == "syncStartedEvent":
            return [UserEvent(user.syncStartedEvent.userID, sync="started")]
        if which == "syncProgressEvent":
            return [UserEvent(user.syncProgressEvent.userID, sync="progress", progress=user.syncProgressEvent.progress)]
        if which == "syncFinishedEvent":
            return [UserEvent(user.syncFinishedEvent.userID, sync="finished")]
        if which in ("userChanged", "userBadEvent"):
            return [self._state_of(getattr(user, which).userID)]
        if which == "userDisconnected":
            name = user.userDisconnected.username
            return [self._state_of(u.id) for u in self._call("GetUserList", self._empty).users if u.username == name]
        return []

    def _state_of(self, user_id: str) -> UserEvent:
        return UserEvent(user_id, state=self.user(user_id).state)


def _channel(grpc: Any, cfg: dict[str, Any]) -> Any:
    """TLS under the certificate Bridge wrote, over its file socket when it made one, else its loopback port."""
    creds = grpc.ssl_channel_credentials(root_certificates=cfg["cert"].encode())
    target = f"unix:{cfg['fileSocketPath']}" if cfg.get("fileSocketPath") else f"127.0.0.1:{cfg['port']}"
    return grpc.secure_channel(target, creds, options=(("grpc.ssl_target_name_override", "127.0.0.1"),))


def _user(user: Any) -> UserInfo:
    return UserInfo(user.id, _STATES.get(user.state, "locked"), user.splitMode, tuple(user.addresses),
                    bytes(user.password).decode(errors="replace"))
