import datetime
import itertools
import sys
import time
import uuid
from collections import deque
from pathlib import Path

import numpy as np
from event_model import StreamRange, compose_stream_resource
from ophyd import AreaDetector
from ophyd import Component as Cpt
from ophyd import (
    DetectorBase,
    Device,
    DeviceStatus,
    EpicsSignal,
    EpicsSignalRO,
    ImagePlugin,
    Kind,
    ROIPlugin,
    Signal,
    SingleTrigger,
    StatsPlugin,
)
from ophyd.areadetector.base import NDDerivedSignal
from ophyd.areadetector.filestore_mixins import (
    FileStoreIterativeWrite,
    FileStorePluginBase,
    resource_factory,
)
from ophyd.areadetector.plugins import ImagePlugin_V33, TIFFPlugin_V33
from ophyd.sim import new_uid
from PIL import Image, ImageDraw, ImageFont

# class ExternalFileReference(Signal):
#     """
#     A pure software Signal that describe()s an image in an external file.
#     """

#     def describe(self):
#         resource_document_data = super().describe()
#         resource_document_data[self.name].update(
#             {
#                 "external": "FILESTORE:",
#                 "dtype": "array",
#             }
#         )
#         return resource_document_data


class FileStoreTIFF(FileStorePluginBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filestore_spec = "BMM_USBCAM"  # spec name stored in resource doc
        self.stage_sigs.update(
            [
                # ("file_template", "%s%s_%6.6d.jpeg"),
                ("file_write_mode", "Single"),
            ]
        )
        # 'Single' file_write_mode means one image : one file.
        # It does NOT mean that 'num_images' is ignored.

    def describe(self):
        ret = super().describe()
        key = self.name
        color_mode = self.parent.cam.color_mode.get(as_string=True)
        if not ret:
            ret = {key: {}}
        ret[key].update(
            {
                "shape": [
                    # self.parent.cam.num_images.get(),
                    self.array_size.depth.get(),  # should be width, need a PR in the relevant AD repo?
                    self.array_size.height.get(),
                    3,  # number of channels (RGB)
                ],
                "dtype": "array",
                "source": self.parent.name,
                "external": "STREAM:",
            }
        )

        cam_dtype = self.parent.cam.data_type.get(as_string=True)
        type_map = {"UInt8": "|u1", "UInt16": "<u2", "Float32": "<f4", "Float64": "<f8"}
        if cam_dtype in type_map:
            ret[key].setdefault("dtype_str", type_map[cam_dtype])

        return ret

    def stage(self):
        ret = super().stage()
        # this over-rides the behavior is the base stage
        # self._fn = self._fp

        full_file_name = (
            self.full_file_name.get()
        )  # TODO: .replace("_000.jpg", "_%3.3d.jpg")

        hostname = "localhost"  # TODO: consider replacing with the IOC host.
        uri = f"file://{hostname}/{str(full_file_name).strip('/')}"

        self._stream_resource_document, self._stream_datum_factory = (
            compose_stream_resource(
                data_key=self.name,
                # For event-model<1.21.0:
                # spec=self.filestore_spec,
                # root="/",
                # resource_path=full_file_name,
                # resource_kwargs={"resource_path": full_file_name},
                # For event-model>=1.21.0:
                mimetype="image/tiff",
                uri=uri,
                parameters={},
            )
        )
        print(self._stream_resource_document)

        self._asset_docs_cache.append(
            ("stream_resource", self._stream_resource_document)
        )

        # resource_kwargs = {
        #     "resource_path": resource_path
        # }
        # self._generate_resource(resource_kwargs)
        # self._asset_docs_cache[0][1].pop("resource_path")  # Temporary fix to avoid collision with the kwarg in 'BMM_JPEG_HANDLER'.
        return ret

    def generate_datum(self, *args, **kwargs):
        stream_datum_document = self._stream_datum_factory(
            StreamRange(start=0, stop=1),
        )
        self._asset_docs_cache.append(("stream_datum", stream_datum_document))
        return ""

    def collect_asset_docs(self):
        """The method to collect resource/datum documents."""
        items = list(self._asset_docs_cache)
        self._asset_docs_cache.clear()
        yield from items


# class FileStoreJPEGIterativeWrite(FileStoreJPEG, FileStoreIterativeWrite):
#     pass


class TIFFPluginWithFileStore(TIFFPlugin_V33, FileStoreTIFF):
    """Add this as a component to detectors that write JPEGs."""

    ...


# class StandardCameraWithJPEG(AreaDetector):
#     jpeg = Cpt(JPEGPluginWithFileStore,
#                suffix='JPEG1:',
#                write_path_template=f'/nsls2/data3/bmm/proposal/{md["cycle"]}/{md["data_session"]}assets/usbcam-1/%Y/%m/%d/',
#                root=f'/nsls2/data3/bmm/proposal/{md["cycle"]}/{md["data_session"]}/assets')


# class JPEGPluginEnsuredOn(JPEGPluginWithFileStore):
#     """Add this as a component to detectors that do not write JPEGs."""
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         # self.stage_sigs.update([('auto_save', 'No')])


class CAMERA(SingleTrigger, AreaDetector):  # SingleTrigger, Device, AreaDetector
    image = Cpt(ImagePlugin, "image1:")
    tiff1 = Cpt(
        TIFFPluginWithFileStore,  # 'TIFF1:')
        suffix="TIFF1:",
        write_path_template=f"/nsls2/data/tst/legacy/mock-proposals/pass-000000/uvc-cam1",
        root=f"/nsls2/data/tst/legacy/mock-proposals/pass-000000",
    )

    tiff_filepath = Cpt(EpicsSignal, "TIFF1:FilePath")
    tiff_filetemplate = Cpt(EpicsSignal, "TIFF1:FileTemplate")
    tiff_filename = Cpt(EpicsSignal, "TIFF1:FileName")
    tiff_autoincrement = Cpt(EpicsSignal, "TIFF1:AutoIncrement")
    tiff_fileformat = Cpt(EpicsSignal, "TIFF1:FileTemplate")
    tiff_writefile = Cpt(EpicsSignal, "TIFF1:WriteFile")
    tiff_create_dir_depth = Cpt(EpicsSignal, "TIFF1:CreateDirectory")
    tiff_autosave = Cpt(EpicsSignal, "TIFF1:AutoSave")

    def __init__(self, *args, root_dir=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_sigs.update(
            [
                ("cam.image_mode", "Single"),
            ]
        )
        self.kind = Kind.normal
        self.tiff1.kind = Kind.normal
        if root_dir is None:
            msg = "The 'root_dir' kwarg cannot be None"
            raise RuntimeError(msg)
        self._root_dir = root_dir
        # self._resource_document, self._datum_factory = None, None
        # self._asset_docs_cache = deque()

        # self._SPEC = "BMM_USBCAM"
        # self.image.name = self.name

    def _update_paths(self):
        self._root_dir = self.root_path_str

    @property
    def root_path_str(self):
        root_path = f"/nsls2/data/tst/legacy/mock-proposals/pass-000000"
        return root_path

    # def collect_asset_docs(self):
    #     """The method to collect resource/datum documents."""
    #     items = list(self._asset_docs_cache)
    #     self._asset_docs_cache.clear()
    #     yield from items

    def stage(self):
        # self._update_paths()
        self.tiff1.auto_save.put(1)
        super().stage()

    #     # Clear asset docs cache which may have some documents from the previous failed run.
    #     self._asset_docs_cache.clear()

    #     # date = datetime.datetime.now()
    #     assets_dir = self.name
    #     data_file_no_ext = f"{self.name}_{new_uid()}"
    #     data_file_with_ext = f"{data_file_no_ext}.jpeg"

    #     self._resource_document, self._datum_factory, _ = compose_resource(
    #         start={"uid": "needed for compose_resource() but will be discarded"},
    #         spec="BMM_JPEG_HANDLER",
    #         root=self._root_dir,
    #         resource_path=str(Path(assets_dir) / Path(data_file_with_ext)),
    #         resource_kwargs={},
    #     )

    #     # now discard the start uid, a real one will be added later
    #     self._resource_document.pop("run_start")
    #     self._asset_docs_cache.append(("resource", self._resource_document))

    #     # Update AD IOC parameters:
    #     self.jpeg_filepath.put(str(Path(self._root_dir) / Path(assets_dir)))
    #     self.jpeg_filename.put(data_file_with_ext)
    #     #self.ioc_stage.put(1)

    def describe(self):
        res = super().describe()
        # if self.name == 'usbcam-1':
        #     res[self.image.name].update(
        #         {"shape": (1080, 1920), "dtype_str": "<f4"}
        #     )
        # elif self.name == 'usbcam-2':
        #     res[self.image.name].update(
        #         {"shape": (600, 800), "dtype_str": "<f4"}
        #     )
        return res

    def unstage(self):
        # self._resource_document = None
        # self._datum_factory = None
        # self.ioc_stage.put(0)

        ## turn off file saving and return the camera to continuous mode for viewing
        super().unstage()
        self.tiff1.auto_save.put(0)
        self.cam.image_mode.put(2)
        self.cam.acquire.put(1)

    def stop(self, success=False):
        self.tiff1.auto_save.put(0)
        return super().stop(success=success)

    # def _update_paths(self):
    #     self.jpeg_filepath.put(f"/nsls2/data3/bmm/proposals/{md['cycle']}/{md['data_session']}/assets/{self.name}/{datetime.datetime.now().strftime('%Y/%m/%d')}")

    # def collect_asset_docs(self):
    #     """The method to collect resource/datum documents."""
    #     items = list(self._asset_docs_cache)
    #     self._asset_docs_cache.clear()
    #     yield from items

    # def stage(self, *args, **kwargs):
    #     self._update_paths()
    #     self.jpeg_filename.put(str(uuid.uuid4()))
    #     # self._rel_path_template = f"{self.jpeg_filename.get()}_%d.jpg"
    #     # self._root = self.jpeg_filepath.get()
    #     # resource, self._datum_factory = resource_factory(
    #     #     self._SPEC, self._root, self._rel_path_template, {}, "posix")
    #     # self._asset_docs_cache.append(('resource', resource))
    #     self._counter = itertools.count()

    #     super().stage(*args, **kwargs)
    #     # # Clear asset docs cache which may have some documents from the previous failed run.
    #     # self._asset_docs_cache.clear()

    #     # self._resource_document, self._datum_factory, _ = compose_resource(
    #     #     start={"uid": "needed for compose_resource() but will be discarded"},
    #     #     spec="BMM_JPEG_HANDLER",
    #     #     root=self._root_dir,
    #     #     resource_path=str(Path(assets_dir) / Path(data_file_with_ext)),
    #     #     resource_kwargs={},
    #     # )


uvc_cam1 = CAMERA("XF:31ID1-ES{UVC-Cam:1}", name="uvc-cam1")
