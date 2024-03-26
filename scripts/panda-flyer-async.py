#!/usr/bin/env python3

import asyncio
import time
from enum import Enum
from typing import AsyncGenerator, AsyncIterator, Dict, Optional, Sequence
from unittest.mock import Mock

import bluesky.plan_stubs as bps
from bluesky import RunEngine
from bluesky.protocols import Descriptor, StreamAsset
from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop
from event_model import ComposeStreamResourceBundle, compose_stream_resource
from IPython import get_ipython
from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    HardwareTriggeredFlyable,
    SignalRW,
    SimSignalBackend,
    TriggerLogic,
)
from ophyd_async.core.detector import DetectorTrigger, DetectorWriter, StandardDetector
from ophyd_async.core.device import DeviceCollector, DeviceVector
from ophyd_async.core.flyer import TriggerLogic
from ophyd_async.core.signal import SignalRW, observe_value
from ophyd_async.panda.panda import PandA

RE = RunEngine()

get_ipython().run_line_magic("autoawait", "call_in_bluesky_event_loop")


# class TriggerState(str, Enum):
#     null = "null"
#     preparing = "preparing"
#     starting = "starting"
#     stopping = "stopping"


# class PandATriggerLogic(TriggerLogic[int]):
#     def __init__(self):
#         self.state = TriggerState.null

#     def trigger_info(self, value: int) -> TriggerInfo:
#         return TriggerInfo(
#             num=value, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
#         )

#     async def prepare(self, value: int):
#         self.state = TriggerState.preparing
#         return value

#     async def start(self):
#         self.state = TriggerState.starting

#     async def stop(self):
#         self.state = TriggerState.stopping


# class PandAHDF5Writer(DetectorWriter):
#     def __init__(self, name: str, shape: Sequence[int], fields):
#         self.dummy_signal = SignalRW(backend=SimSignalBackend(int, source="test"))
#         self._shape = shape
#         self._name = name
#         self._file: Optional[ComposeStreamResourceBundle] = None
#         self._last_emitted = 0
#         self.index = 0
#         self._type_map = {"int32": "<i4", "float32": "<f4", "float64": "<f8"}
#         self._fields = fields

#     async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
#         return {
#             self._name: Descriptor(
#                 source="PANDA",
#                 shape=self._shape,
#                 dtype="array",
#                 dtype_str=value["dtype_str"],
#                 external="STREAM:",
#             )
#         }

#     async def observe_indices_written(
#         self, timeout=DEFAULT_TIMEOUT
#     ) -> AsyncGenerator[int, None]:
#         num_captured: int
#         async for num_captured in observe_value(self.dummy_signal, timeout):
#             yield num_captured

#     async def get_indices_written(self) -> int:
#         return self.index

#     async def collect_stream_docs(
#         self, indices_written: int
#     ) -> AsyncIterator[StreamAsset]:
#         if indices_written:
#             if not self._file:
#                 self._file = compose_stream_resource(
#                     spec="AD_HDF5_SWMR_SLICE",
#                     root="/",
#                     data_key=self._name,
#                     resource_path="",
#                     resource_kwargs={
#                         "path": "",
#                         "multiplier": 1,
#                         "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
#                     },
#                 )
#                 yield "stream_resource", self._file.stream_resource_doc

#             if indices_written >= self._last_emitted:
#                 indices = dict(
#                     start=self._last_emitted,
#                     stop=indices_written,
#                 )
#                 self._last_emitted = indices_written
#                 self._last_flush = time.monotonic()
#                 yield "stream_datum", self._file.compose_stream_datum(indices)

#     async def close(self) -> None:
#         self._file = None


# class PandANSLS2(PandA):

#     def __init__(self, *args, writer=None, **kwargs):
#         self._fields = {}
#         self._writer = writer
#         super().__init__(*args, **kwargs)

#     async def find_all_selected_captures(self):
#         selected_captures = []

#         for name, block_type in dict(self.children()).items():
#             blocks_dict = {"1": block_type}
#             if isinstance(block_type, DeviceVector):
#                 blocks_dict = dict(block_type.children())
#             for number, block in blocks_dict.items():
#                 for signal_name, signal in dict(block.children()).items():
#                     print(f"Checking signal: {signal_name} in block {name}{number}")
#                     if signal_name.endswith("_capture"):
#                         signal_val = await signal.get_value()
#                         if signal_val.value != "No":
#                             print(
#                                 f"*******Saving signal: {signal_name} in block {name}{number}"
#                             )
#                             selected_captures.append(signal)
#         return selected_captures

#     def create_fields(self):

#         for i, cpt in enumerate(self.positions.component_names):
#             cpt_obj = getattr(self.panda.positions, cpt)
#             capture = cpt_obj.capture.get()
#             param_name = cpt_obj.param_name.get()
#             if capture == "Value":
#                 self.fields[f"{param_name.replace(':', '_').lower()}"] = {
#                     "value": f"{param_name.replace(':', '.')}.{capture}",  # e.g., "COUNTER1.OUT.Value",
#                     "dtype_str": self._writer._type_map[
#                         "float64"
#                     ],  # TODO: figure out how to assign dtypes properly based on the info from the IOC.
#                 }


if __name__ == "__main__":
    from ophyd_async.core import Device, StaticDirectoryProvider
    from ophyd_async.panda.writers import PandaHDFWriter

    async def hello_panda():
        async with DeviceCollector():
            panda3 = PandA("XF:31ID1-ES{PANDA:3}", name="panda3")
            # await panda3.connect()

        async with DeviceCollector():
            dir_prov = StaticDirectoryProvider(
                "/nsls2/data/tst/legacy/mock-proposals/2024-1/pass-000000",
                "test-ophyd-async3",
            )
            writer3 = PandaHDFWriter(
                "XF:31ID1-ES{PANDA:3}",
                dir_prov,
                lambda: "test-panda",
                panda_device=panda3,
            )

        for name, obj in dict(panda3.data.children()).items():
            print(f"{name}: {await obj.read()}")

        await writer3.open()
        await panda3.pcap.arm.set(1)
        await asyncio.sleep(5)
        await panda3.pcap.arm.set(0)
        await asyncio.sleep(1)
        await writer3.close()

        return panda3, writer3

    panda3, writer3 = asyncio.run(hello_panda())

    print(panda3.__dir__())
    print(writer3.__dir__())
