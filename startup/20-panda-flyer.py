print(f"Loading file {__file__!r} ...")

import asyncio
import datetime
import itertools
import time as ttime
from collections import deque
from enum import Enum
from pathlib import Path
from pprint import pprint
from typing import AsyncGenerator, AsyncIterator, Dict, List, Optional

from event_model import compose_resource
from ophyd.status import SubscriptionStatus


class PandaFlyer:
    """This flyer works with the 'rotations_sim_04'.

    Simulation mode with no motor input for now (2024-01-26)."""

    def __init__(self, panda, motor=None, root_dir=None, verbose=False, **kwargs):
        self.name = "PandaFlyer"
        if root_dir is None:
            raise ValueError("'root_dir' should be specified")
        self._root_dir = root_dir
        self._resource_document, self._datum_factory = None, None
        self._asset_docs_cache = deque()

        self.panda = panda
        self.motor = motor

        # self.t_period = 0.00002
        self.theta0 = 10
        self.n_proj = 161
        self.n_series = 3

        # Objects needed for the bluesky documents generation:
        self._asset_docs_cache = None
        self._resource_document = None
        self._datum_factory = None

        type_map = {"int32": "<i4", "float32": "<f4", "float64": "<f8"}

        # TODO: figure out how to add those parameters dynamically to the self.fields.
        self.fields = {
            "pcap_gate_duration": {
                "value": "PCAP.GATE_DURATION.Value",
                "dtype_str": type_map["float64"],
            },
            "pcap_ts_trig": {
                "value": "PCAP.TS_TRIG.Value",
                "dtype_str": type_map["float64"],
            },
        }

        for i, cpt in enumerate(self.panda.positions.component_names):
            cpt_obj = getattr(self.panda.positions, cpt)
            capture = cpt_obj.capture.get()
            param_name = cpt_obj.param_name.get()
            if capture == "Value":
                self.fields[f"{param_name.replace(':', '_').lower()}"] = {
                    "value": f"{param_name.replace(':', '.')}.{capture}",  # e.g., "COUNTER1.OUT.Value",
                    "dtype_str": type_map[
                        "float64"
                    ],  # TODO: figure out how to assign dtypes properly based on the info from the IOC.
                }
        if verbose:
            pprint(self.fields)

    def _prepare(self, params=None):  # TODO: pass inputs via params
        """Prepare scanning parameters."""

        steps_per_turn = 8000
        comp2_start = 1  # Can not be ZERO
        steps_per_deg = steps_per_turn / 360
        theta0_steps = int(self.theta0 * steps_per_deg - comp2_start)

        if theta0_steps < 0:
            theta0_steps += steps_per_turn
        elif theta0_steps >= steps_per_turn:
            theta0_steps -= steps_per_turn
        print(f"{theta0_steps = }")

        self.panda.pcomp1.pre_start.set(0).wait()
        self.panda.pcomp1.start.set(theta0_steps).wait()
        self.panda.pcomp1.width.set(1).wait()
        self.panda.pcomp1.step.set(1000000).wait()
        self.panda.pcomp1.pulses.set(1).wait()

        proj_step_ = steps_per_turn / 2 / (self.n_proj - 1)
        proj_step = int(round(proj_step_))
        if abs(proj_step - proj_step_) > 1e-3:
            print(f"proj_step_ = {proj_step_}")
            raise ValueError("The step between projections is not integer")

        print(f"proj_step={proj_step} n_proj={self.n_proj}")

        self.panda.pcomp2.pre_start.set(0).wait()
        self.panda.pcomp2.start.set(comp2_start).wait()
        self.panda.pcomp2.width.set(20).wait()
        self.panda.pcomp2.step.set(proj_step).wait()
        self.panda.pcomp2.pulses.set(self.n_proj).wait()

    def kickoff(self):
        """Kickoff the acquisition process."""
        # Prepare parameters:
        self._prepare()
        self._asset_docs_cache = deque()
        self._datum_docs = {}
        self._counter = itertools.count()

        # Prepare 'resource' factory.
        now = datetime.datetime.now()
        self.fl_path = self._root_dir
        self.fl_name = f"panda_rbdata_{now.strftime('%Y%m%d_%H%M%S')}.h5"

        resource_path = self.fl_name
        self._resource_document, self._datum_factory, _ = compose_resource(
            start={"uid": "needed for compose_resource() but will be discarded"},
            spec="PANDA",
            root=self._root_dir,
            resource_path=resource_path,
            resource_kwargs={},
        )
        # now discard the start uid, a real one will be added later
        self._resource_document.pop("run_start")
        self._asset_docs_cache.append(("resource", self._resource_document))

        for key, value in self.fields.items():
            datum_document = self._datum_factory(datum_kwargs={"field": value["value"]})
            self._asset_docs_cache.append(("datum", datum_document))
            self._datum_docs[key] = datum_document

        # Kickoff panda process:
        print(f"Starting acquisition ...")

        self.panda.bits.A.set(1).wait()

        self.panda.data.hdf_directory.set(self.fl_path).wait()
        self.panda.data.hdf_file_name.set(self.fl_name).wait()
        self.panda.data.flush_period.set(0.5).wait()

        if not self.n_series:
            self.panda.bits.B.set(1).wait()
            self.panda.data.capture_mode.set("FOREVER").wait()
        else:
            self.panda.bits.B.set(0).wait()
            self.panda.counter3.start.set(0).wait()
            self.panda.counter3.min.set(0).wait()
            self.panda.counter3.step.set(1).wait()
            self.panda.counter3.max.set(self.n_series).wait()

            self.panda.data.capture_mode.set("FIRST_N").wait()
            self.panda.data.num_capture.set(self.n_proj * self.n_series).wait()

        self.panda.data.capture.set(1).wait()

        st = self.panda.pcap.arm.set(1)

        ttime.sleep(1)

        # print(f"HDF5 status: {self.panda.hdf5.status.read()}")
        # print(f"HDF5 file path: {self.panda.hdf5.file_path.read()}")

        return st

    def complete(self):
        """Wait for the acquisition process started in kickoff to complete."""
        ...

        # Wait until done
        def done_callback(value, old_value, **kwargs):
            # print(f"Running... {old_value} --> {value}, {kwargs}")
            if old_value == 1 and value == 0:  # 1=active, 0=inactive
                # print(f"Done: {old_value} --> {value}, {kwargs}")
                self.panda.pcap.arm.set(0).wait()
                self.panda.data.capture.set(0).wait()
                return True
            return False

        st = SubscriptionStatus(self.panda.pcap.active, done_callback, run=False)
        return st

    def describe_collect(self):
        """Describe the data structure."""
        return_dict = {"primary": {}}

        for key, value in self.fields.items():
            return_dict["primary"].update(
                {
                    key: {
                        "source": "PANDA",
                        "dtype": "array",
                        "dtype_str": value["dtype_str"],
                        "shape": [
                            self.n_proj * self.n_series
                        ],  # TODO: figure out variable shape
                        "external": "FILESTORE:",
                    }
                }
            )

        return return_dict

    def collect(self):

        data_dict = {
            key: datum_doc["datum_id"] for key, datum_doc in self._datum_docs.items()
        }

        now = ttime.time()  # TODO: figure out how to get it from PandABox (maybe?)
        yield {
            "data": data_dict,
            "timestamps": {key: now for key in self._datum_docs},
            "time": now,
            "filled": {key: False for key in self._datum_docs},
        }

    def collect_asset_docs(self):
        """The method to collect resource/datum documents."""
        items = list(self._asset_docs_cache)
        self._asset_docs_cache.clear()
        yield from items

    def stop(self):
        """TODO: Clean up the state."""
        ...


panda_flyer = PandaFlyer(pnd, root_dir=PROPOSAL_DIR)
