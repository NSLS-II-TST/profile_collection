print(f"Loading file {__file__!r} ...")


import asyncio
from dataclasses import dataclass
from enum import Enum

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    DeviceCollector,
    HardwareTriggeredFlyable,
    ShapeProvider,
    SignalRW,
    SimSignalBackend,
    StaticDirectoryProvider,
    TriggerInfo,
    TriggerLogic,
    UUIDDirectoryProvider,
    set_sim_value,
)
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.areadetector.controllers.vimba_controller import VimbaController
from ophyd_async.epics.areadetector.drivers.vimba_driver import VimbaDriver
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF

MANTA_PV_PREFIX = "XF:31ID1-ES{GigE-Cam:1}"


class TriggerState(str, Enum):
    null = "null"
    preparing = "preparing"
    starting = "starting"
    stopping = "stopping"


@dataclass
class MantaTriggerSetup:
    num_images: int
    exposure_time: float


class MantaTriggerLogic(TriggerLogic[int]):
    def __init__(self):
        self.state = TriggerState.null

    def trigger_info(self, setup) -> TriggerInfo:
        return TriggerInfo(
            num=setup.num_images,
            trigger=DetectorTrigger.edge_trigger,
            deadtime=0.1,
            livetime=setup.exposure_time,
        )

    async def prepare(self, value: int):
        self.state = TriggerState.preparing
        return value

    async def start(self):
        self.state = TriggerState.starting

    async def stop(self):
        self.state = TriggerState.stopping


manta_trigger_logic = MantaTriggerLogic()


class MantaShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self):
        return (544, 728)  # y, x


def instantiate_panda_async():
    with DeviceCollector():
        manta_async = VimbaDriver(MANTA_PV_PREFIX + "cam1:")
        hdf_plugin_manta = NDFileHDF(MANTA_PV_PREFIX + "HDF1:", name="manta_hdf_plugin")

    with DeviceCollector():
        dir_prov = UUIDDirectoryProvider(PROPOSAL_DIR)
        manta_writer = HDFWriter(
            hdf_plugin_manta,
            dir_prov,
            lambda: "lab3-manta",
            MantaShapeProvider(),
        )
        print_children(manta_async)

    return manta_async, manta_writer


manta_async, manta_writer = instantiate_panda_async()
manta_controller = VimbaController(manta_async)

manta_standard_det = StandardDetector(
    manta_controller, manta_writer, name="manta_standard_det"
)


manta_flyer = HardwareTriggeredFlyable(manta_trigger_logic, [], name="manta_flyer")


def manta_stage():
    yield from bps.stage(manta_standard_det)
    yield from bps.sleep(5)


def manta_fly(
    num=10,
):  # Note: 724 points are specific for the "rotation_sim_04" panda config!
    yield from bps.stage_all(manta_standard_det, manta_flyer)
    assert manta_flyer._trigger_logic.state == TriggerState.stopping
    yield from bps.prepare(manta_flyer, num, wait=True)
    yield from bps.prepare(manta_standard_det, manta_flyer.trigger_info, wait=True)

    detector = manta_standard_det
    # detector.controller.disarm.assert_called_once  # type: ignore

    yield from bps.open_run()

    yield from bps.kickoff(manta_flyer)
    yield from bps.kickoff(detector)

    yield from bps.complete(manta_flyer, wait=True, group="complete")
    yield from bps.complete(detector, wait=True, group="complete")

    # Manually incremenet the index as if a frame was taken
    # detector.writer.index += 1

    done = False
    while not done:
        try:
            yield from bps.wait(group="complete", timeout=0.5)
        except TimeoutError:
            pass
        else:
            done = True
        yield from bps.collect(
            manta_standard_det,
            stream=True,
            return_payload=False,
            name="main_stream",
        )
        yield from bps.sleep(0.01)

    yield from bps.wait(group="complete")
    val = yield from bps.rd(manta_writer.hdf.num_captured)
    print(f"{val = }")
    yield from bps.close_run()

    yield from bps.unstage_all(manta_flyer, manta_standard_det)
