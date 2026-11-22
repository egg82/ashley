"""Her tools for a camera's live feed on the screens, as the model is offered them. Both change what people see, so, as
`screen_add` and the other screen tools are, they are `outside=False` (the result is her own confirmation) and judged."""

from ..inference.model import ToolSpec

SHOW = "screen_show_camera"
CLEAR = "screen_clear_camera"
INSTRUCTIONS = ("screen_show_camera puts a camera's live video on the screens someone is looking at (the hall screen "
                "when someone is home, and the page of anyone away who has it open), by the camera id `cameras` gives. "
                "It slides in, plays without sound, leaves by itself after a short while and can be swiped away. Use it "
                "when seeing the camera matters now, say so in a line, and never for a look you only need yourself: "
                "camera_look is that. screen_clear_camera takes it off every screen. A camera that is not one you may look "
                "through, or gives no live video, is refused, and so is a show that no screen in reach is open and in the "
                "foreground to receive: say nobody saw it.")


def specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(SHOW, "Put the camera's live video on the screens that are open and in the foreground. Returns how many "
                 "screens it went to; a refusal, `no_one_looking`, when no screen in reach is open and in the "
                 "foreground: nobody saw it, so say so.",
                 {"type": "object", "required": ["camera"], "properties": {
                     "camera": {"type": "string", "description": "the camera, by the id cameras gives"}}},
                 outside=False, tier="judged"),
        ToolSpec(CLEAR, "Take the camera's live video off every screen.", {"type": "object", "properties": {}},
                 outside=False, tier="judged"))
