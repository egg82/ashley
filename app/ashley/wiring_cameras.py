"""The Cameras port wired: the cameras of every service that serves it, behind one router."""

from . import services
from .bambuddy import cameras as bambuddy_cameras
from .cameras.cameras import Cameras
from .cameras.routed import RoutedCameras
from .herdr import cameras as herdr_cameras
from .home_assistant import cameras as home_assistant_cameras


def register(max_recordings: int) -> None:
    """`max_recordings`: the most of a camera's recordings she is listed (`ashley.looks.config`)."""
    services.register(Cameras, RoutedCameras({home_assistant_cameras.NAME: home_assistant_cameras.HaCameras(),
                                              bambuddy_cameras.NAME: bambuddy_cameras.BambuddyCameras(),
                                              herdr_cameras.NAME: herdr_cameras.HerdrCameras()},
                                             max_recordings))
