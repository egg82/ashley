"""Home Assistant's camera WebRTC commands behind the House port's live feed (`ashley.home_assistant.ha_house.HaHouse`),
against a stand-in on a real socket speaking Home Assistant's documented shapes (`ha_live_support`): the client
configuration is read into ICE servers and a data channel; an offer is sent as `camera/webrtc/offer` with the camera and
SDP and its events arrive as session, answer and candidate signals (an event of a type this does not read is skipped);
the subscription stays open exactly as long as the context and Home Assistant sees it close; a candidate goes as
`camera/webrtc/candidate` in `RTCIceCandidateInit` fields; a camera without WebRTC is a rejection, not an outage; an
unreachable or refusing house is HouseUnavailable."""

import asyncio

import pytest
from ashley.cameras.model import (Candidate, IceServer, LiveAnswer, LiveCandidate, LiveConfig, LiveSession, LiveSignal)
from ashley.home_assistant.ha_house import HaHouse
from ashley.home_assistant.house import HouseRejected, HouseUnavailable
from ha_live_support import ANSWER_SDP, CAMERA, PLAIN, SESSION, TOKEN, Ha, client_for, go, ha as ha, settings, stand_in as stand_in


def house(ha: Ha, token: str = TOKEN) -> HaHouse:
    return HaHouse(client_for(ha.url, token), settings())


def test_the_client_configuration_is_ice_servers_and_a_data_channel(ha: Ha) -> None:
    got = go(house(ha).live_config(CAMERA))
    assert got == LiveConfig((IceServer(("stun:stun.example.test:3478",), None, None),
                              IceServer(("turn:turn.example.test:3478",), "zq-user", "zq-secret")), "dataSendChannel")
    assert ha.commands == [{"type": "camera/webrtc/get_client_config", "entity_id": CAMERA}]


def test_an_offer_streams_session_answer_and_candidates_and_the_feed_ends_with_the_context(ha: Ha) -> None:
    async def scenario() -> list[LiveSignal]:
        got: list[LiveSignal] = []
        async with house(ha).live_feed(CAMERA, "v=0 offer") as signals:
            async for signal in signals:
                got.append(signal)
                if len(got) == 3:
                    break
            assert ha.open_streams == 1 and ha.closed_streams == 0
        for _ in range(100):   # Home Assistant notices the close on its side
            if ha.closed_streams:
                break
            await asyncio.sleep(0.01)
        return got

    got = go(scenario())
    assert got == [LiveSession(SESSION), LiveAnswer(ANSWER_SDP), LiveCandidate(Candidate(
        "candidate:1 1 udp 2113937151 192.0.2.7 50000 typ host", "0", 0))]
    assert ha.commands == [{"type": "camera/webrtc/offer", "entity_id": CAMERA, "offer": "v=0 offer"}]
    assert ha.closed_streams == 1


def test_a_candidate_goes_as_the_init_fields_home_assistant_takes(ha: Ha) -> None:
    go(house(ha).live_candidate(CAMERA, SESSION, Candidate("candidate:2 1 udp 1 192.0.2.9 50001 typ host", "0", 0, "frag")))
    go(house(ha).live_candidate(CAMERA, SESSION, Candidate("candidate:3 1 udp 1 192.0.2.9 50002 typ host", None, None)))
    assert ha.commands == [
        {"type": "camera/webrtc/candidate", "entity_id": CAMERA, "session_id": SESSION, "candidate": {
            "candidate": "candidate:2 1 udp 1 192.0.2.9 50001 typ host", "sdpMid": "0", "sdpMLineIndex": 0,
            "usernameFragment": "frag"}},
        {"type": "camera/webrtc/candidate", "entity_id": CAMERA, "session_id": SESSION, "candidate": {
            "candidate": "candidate:3 1 udp 1 192.0.2.9 50002 typ host", "sdpMid": None, "sdpMLineIndex": None}}]


@pytest.mark.parametrize("ask", ["config", "offer", "candidate"])
def test_a_camera_without_webrtc_is_rejected_by_each_command(ha: Ha, ask: str) -> None:
    async def scenario() -> None:
        made = house(ha)
        if ask == "config":
            await made.live_config(PLAIN)
        elif ask == "candidate":
            await made.live_candidate(PLAIN, SESSION, Candidate("candidate:4", None, None))
        else:
            async with made.live_feed(PLAIN, "v=0"):
                pytest.fail("entered a feed that Home Assistant refused")

    with pytest.raises(HouseRejected, match="does not support WebRTC"):
        go(scenario())


def test_a_refused_token_or_no_house_is_unavailable_not_a_rejection(ha: Ha) -> None:
    async def offer(made: HaHouse) -> None:
        async with made.live_feed(CAMERA, "v=0"):
            pytest.fail("entered a feed with a refused token")

    with pytest.raises(HouseUnavailable):
        go(offer(house(ha, "wrong-token")))
    with pytest.raises(HouseUnavailable):
        go(house(ha, "wrong-token").live_config(CAMERA))
    dead = HaHouse(client_for("http://127.0.0.1:9"), settings())
    with pytest.raises(HouseUnavailable):
        go(dead.live_config(CAMERA))
