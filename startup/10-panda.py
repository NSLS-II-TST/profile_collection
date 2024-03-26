print(f"Loading file {__file__!r} ...")

import asyncio
import datetime
import json
import time as ttime
from enum import Enum
from pathlib import Path
from threading import Thread
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
from bluesky import RunEngine
from bluesky.utils import ProgressBarManager
from epics import caget, caput
from ophyd import Component as Cpt
from ophyd import Device, EpicsMotor, EpicsPathSignal, EpicsSignal, EpicsSignalWithRBV
from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    HardwareTriggeredFlyable,
    SignalRW,
    SimSignalBackend,
    StaticDirectoryProvider,
    TriggerInfo,
    TriggerLogic,
    UUIDDirectoryProvider,
)
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.device import DeviceCollector
from ophyd_async.panda.panda import PandA
from ophyd_async.panda.panda_controller import PandaPcapController
from ophyd_async.panda.writers import PandaHDFWriter


class DATA(Device):
    hdf_directory = Cpt(EpicsSignal, "HDFDirectory", string=True)
    hdf_file_name = Cpt(EpicsSignal, "HDFFileName", string=True)
    num_capture = Cpt(EpicsSignal, "NumCapture")
    flush_period = Cpt(EpicsSignal, "FlushPeriod")
    capture = Cpt(EpicsSignal, "Capture")
    capture_mode = Cpt(EpicsSignal, "CaptureMode", string=True)
    status = Cpt(EpicsSignal, "Status", string=True)


class PCOMP(Device):
    pre_start = Cpt(EpicsSignal, "PRE_START")
    start = Cpt(EpicsSignal, "START")
    width = Cpt(EpicsSignal, "WIDTH")
    step = Cpt(EpicsSignal, "STEP")
    pulses = Cpt(EpicsSignal, "PULSES")


class PCAP(Device):
    arm = Cpt(EpicsSignal, "ARM")
    active = Cpt(EpicsSignal, "ACTIVE")


class CLOCK(Device):
    period = Cpt(EpicsSignal, "PERIOD")
    period_units = Cpt(EpicsSignal, "PERIOD:UNITS")


class COUNTER(Device):
    start = Cpt(EpicsSignal, "START")
    step = Cpt(EpicsSignal, "STEP")
    max = Cpt(EpicsSignal, "MAX")
    min = Cpt(EpicsSignal, "MIN")


class INENC(Device):
    val = Cpt(EpicsSignal, "VAL")


class POSITION(Device):
    param_name = Cpt(EpicsSignal, "NAME", string=True)
    value = Cpt(EpicsSignal, "VAL")
    units = Cpt(EpicsSignal, "UNITS", string=True)
    scale = Cpt(EpicsSignal, "SCALE")
    offset = Cpt(EpicsSignal, "OFFSET")
    capture = Cpt(EpicsSignal, "CAPTURE", string=True)


class POSITIONS(Device):
    calc1 = Cpt(POSITION, "0:")
    calc2 = Cpt(POSITION, "1:")
    counter1 = Cpt(POSITION, "2:")
    counter2 = Cpt(POSITION, "3:")
    counter3 = Cpt(POSITION, "4:")
    counter4 = Cpt(POSITION, "5:")
    counter5 = Cpt(POSITION, "6:")
    counter6 = Cpt(POSITION, "7:")
    counter7 = Cpt(POSITION, "8:")
    counter8 = Cpt(POSITION, "9:")
    filter1 = Cpt(POSITION, "10:")
    filter2 = Cpt(POSITION, "11:")
    fmc_in1 = Cpt(POSITION, "12:")
    fmc_in2 = Cpt(POSITION, "13:")
    fmc_in3 = Cpt(POSITION, "14:")
    fmc_in4 = Cpt(POSITION, "15:")
    fmc_in5 = Cpt(POSITION, "16:")
    fmc_in6 = Cpt(POSITION, "17:")
    fmc_in7 = Cpt(POSITION, "18:")
    fmc_in8 = Cpt(POSITION, "19:")
    inenc1 = Cpt(POSITION, "20:")
    inenc2 = Cpt(POSITION, "21:")
    inenc3 = Cpt(POSITION, "22:")
    inenc4 = Cpt(POSITION, "23:")
    pgen1 = Cpt(POSITION, "24:")
    pgen2 = Cpt(POSITION, "25:")
    spf3_pos1 = Cpt(POSITION, "26:")
    spf3_pos2 = Cpt(POSITION, "27:")
    spf3_pos3 = Cpt(POSITION, "28:")
    spf3_pos4 = Cpt(POSITION, "29:")


class PULSE(Device):
    delay_units = Cpt(EpicsSignal, "DELAY:UNITS", string=True)
    delay = Cpt(EpicsSignal, "DELAY")
    width_units = Cpt(EpicsSignal, "WIDTH:UNITS", string=True)
    width = Cpt(EpicsSignal, "WIDTH")


class BITS(Device):
    A = Cpt(EpicsSignal, "A")
    B = Cpt(EpicsSignal, "B")
    C = Cpt(EpicsSignal, "C")
    D = Cpt(EpicsSignal, "D")


class PandA_Ophyd1(Device):
    pcap = Cpt(PCAP, "PCAP:")
    data = Cpt(DATA, "DATA:")
    pcomp1 = Cpt(PCOMP, "PCOMP1:")
    pcomp2 = Cpt(PCOMP, "PCOMP2:")
    clock1 = Cpt(CLOCK, "CLOCK1:")
    clock2 = Cpt(CLOCK, "CLOCK2:")
    counter1 = Cpt(COUNTER, "COUNTER1:")
    counter2 = Cpt(COUNTER, "COUNTER2:")
    counter3 = Cpt(COUNTER, "COUNTER3:")
    inenc1 = Cpt(INENC, "INENC1:")
    inenc2 = Cpt(INENC, "INENC2:")
    pulse2 = Cpt(PULSE, "PULSE2:")
    pulse3 = Cpt(PULSE, "PULSE3:")
    positions = Cpt(POSITIONS, "POSITIONS:")
    bits = Cpt(BITS, "BITS:")


pnd = PandA_Ophyd1(r"XF:31ID1-ES{PANDA:3}:", name="pnd")
# pnd = PandA_Ophyd1("PANDA:3:", name="pnd")  # Panda IOC fails to work with colons (":") in the PV name
# pnd = PandA_Ophyd1("XF31ID1-ES-PANDA-3:", name="pnd")


##########################################################################
#                         _       ____                                   #
#                        | |     |___ \                                  #
#   _ __   __ _ _ __   __| | __ _  __) |_____ __ _ ___ _   _ _ __   ___  #
#  | '_ \ / _` | '_ \ / _` |/ _` ||__ <______/ _` / __| | | | '_ \ / __| #
#  | |_) | (_| | | | | (_| | (_| |___) |    | (_| \__ \ |_| | | | | (__  #
#  | .__/ \__,_|_| |_|\__,_|\__,_|____/      \__,_|___/\__, |_| |_|\___| #
#  | |                                                  __/ |            #
#  |_|                                                 |___/             #
#                                                                        #
##########################################################################


async def print_children(device):
    for name, obj in dict(device.children()).items():
        print(f"{name}: {await obj.read()}")


class TSTPandaHDFWriter(PandaHDFWriter):
    async def open(self, *args, **kwargs):
        desc = await super().open(*args, **kwargs)
        # prefix = self._name_provider()
        for key in desc:
            if "-counter2-out-" in key:
                desc[key]["dtype_str"] = "<i4"
            else:
                desc[key]["dtype_str"] = "<f8"
        return desc


def instantiate_panda_async():
    with DeviceCollector():
        panda3_async = PandA("XF:31ID1-ES{PANDA:3}:", name="panda3_async")

    with DeviceCollector():
        dir_prov = UUIDDirectoryProvider(PROPOSAL_DIR)
        writer3 = TSTPandaHDFWriter(
            "XF:31ID1-ES{PANDA:3}",
            dir_prov,
            lambda: "lab3-panda3",
            panda_device=panda3_async,
        )
        print_children(panda3_async)

    return panda3_async, writer3


panda3_async, writer3 = instantiate_panda_async()


@AsyncStatus.wrap
async def openw(writer):
    describe = await writer.open()


@AsyncStatus.wrap
async def closew(writer):
    await writer.close()


def arm(panda_device):
    yield from bps.mv(panda_device.pcap.arm, 1)
    yield from bps.sleep(5)
    yield from bps.mv(panda_device.pcap.arm, 0)
    yield from bps.sleep(1)


def count_async_panda(panda_device, writer):
    """This works!"""
    asyncio.gather(writer.open())
    yield from arm(panda_device)
    asyncio.gather(writer.close())


def _count_async_panda_wait(panda_device, writer):
    """This runs, but does not create a file."""
    asyncio.wait(writer.open())
    yield from arm(panda_device)
    asyncio.wait(writer.close())


def _count_async_panda_run(panda_device, writer):
    """This does not work at all

    In [3]: RE(count_async_panda_run(panda_device=panda3_async, writer=writer3))
    An exception has occurred, use '%tb verbose' to see the full traceback.
    RuntimeError: asyncio.run() cannot be called from a running event loop
    """
    # asyncio.run(writer.open())
    yield from arm(panda_device)
    # asyncio.run(writer.close())


class TriggerState(str, Enum):
    null = "null"
    preparing = "preparing"
    starting = "starting"
    stopping = "stopping"


class PandATriggerLogic(TriggerLogic[int]):
    def __init__(self):
        self.state = TriggerState.null

    def trigger_info(self, value: int) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=0.1, livetime=0.1
        )

    async def prepare(self, value: int):
        self.state = TriggerState.preparing
        return value

    async def start(self):
        self.state = TriggerState.starting

    async def stop(self):
        self.state = TriggerState.stopping


panda3_trigger_logic = PandATriggerLogic()
pcap_controller = PandaPcapController(panda3_async.pcap)


class PandA3StandardDet(StandardDetector):

    def __init__(
        self,
        pcap_controller: PandaPcapController,
        writer: PandaHDFWriter,
        *args,
        **kwargs,
    ):
        super().__init__(pcap_controller, writer, *args, **kwargs)
        self.pcap_controller = pcap_controller

    async def _wait(self):
        pcap_active = await self.pcap_controller.pcap.active.get_value()
        print(f"{pcap_active=}")
        while pcap_active:
            pcap_active = await self.pcap_controller.pcap.active.get_value()
            print(f"  {pcap_active=}")
            await asyncio.sleep(0.1)

    @AsyncStatus.wrap
    async def complete(self):
        wait_st = AsyncStatus(self._wait())
        # TODO: discuss with Diamond about And and Or statuses.
        return await wait_st


panda3_standard_det = StandardDetector(
    pcap_controller, writer3, name="panda3_standard_det"
)


panda3_flyer = HardwareTriggeredFlyable(panda3_trigger_logic, [], name="panda3_flyer")


def panda3_fly(
    num=724,
):  # Note: 724 points are specific for the "rotation_sim_04" panda config!
    yield from bps.stage_all(panda3_standard_det, panda3_flyer)
    assert panda3_flyer._trigger_logic.state == TriggerState.stopping
    yield from bps.prepare(panda3_flyer, num, wait=True)
    yield from bps.prepare(panda3_standard_det, panda3_flyer.trigger_info, wait=True)

    detector = panda3_standard_det
    # detector.controller.disarm.assert_called_once  # type: ignore

    yield from bps.open_run()

    yield from bps.kickoff(panda3_flyer)
    yield from bps.kickoff(detector)

    yield from bps.complete(panda3_flyer, wait=True, group="complete")
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
            panda3_standard_det,
            stream=True,
            return_payload=False,
            name="main_stream",
        )
        yield from bps.sleep(0.01)
    yield from bps.wait(group="complete")
    val = yield from bps.rd(writer3.hdf.num_captured)
    print(f"{val = }")
    yield from bps.close_run()

    yield from bps.unstage_all(panda3_flyer, panda3_standard_det)


class JSONLWriter:
    def __init__(self, filepath):
        self.file = open(filepath, "w")

    def __call__(self, name, doc):
        json.dump({"name": name, "doc": doc}, self.file)
        self.file.write("\n")
        if name == "stop":
            self.file.close()


def now():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


jlw = JSONLWriter(f"/tmp/export-docs-{now()}.json")
