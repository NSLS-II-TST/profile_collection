print(f"Loading file {__file__!r} ...")

import h5py
from area_detector_handlers import HandlerBase


class PandAHandlerHDF5(HandlerBase):
    """The handler to read HDF5 files produced by PandABox."""

    specs = {"PANDA"}

    def __init__(self, filename):
        self._name = filename

    def __call__(self, field):
        print("reading", field)
        with h5py.File(self._name, "r") as f:
            entry = f[f"/{field}"]
            return entry[:]


# TODO: remove completely when Tiled is used:
# db.reg.register_handler("PANDA", PandAHandlerHDF5, overwrite=True)
