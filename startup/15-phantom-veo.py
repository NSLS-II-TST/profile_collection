
from ophyd import (Component as Cpt, Device,
                   EpicsSignal, EpicsSignalRO, ROIPlugin, OverlayPlugin,
                   Signal, HDF5Plugin)

from ophyd.areadetector.base import EpicsSignalWithRBV as SignalWithRBV, ADComponent as ADCpt
from ophyd.areadetector.cam import CamBase
from ophyd.areadetector.detectors import DetectorBase

from ophyd.areadetector.filestore_mixins import FileStoreTIFFIterativeWrite, FileStoreHDF5IterativeWrite

import bluesky.plan_stubs as bps

from ophyd.status import SubscriptionStatus, DeviceStatus

import time as ttime


class HDF5PluginWithFileStore(HDF5Plugin, FileStoreHDF5IterativeWrite):
    """Add this as a component to detectors that write HDF5s."""
    def get_frames_per_point(self):
        return 1
        # if not self.parent.is_flying:
        #     return self.parent.cam.num_images.get()
        # else:
        #     return 1



class ADPhantomCine(Device):
    """
    Class representing individual CINE file. Up to 16 can be configured for a single camera.

    Typically only one will be used, unless for some reason it is desired to run multiple collections in sequence without a delay to
    download the images in-between
    """

    def __init__(self, *args, cine_number, **kwargs):
        
        self.cine_number = cine_number
        self.cine_name = Cpt(EpicsSignalRO, f'C{self.cine_number}:Name_RBV')
        self.cine_width = Cpt(EpicsSignalRO, f'C{self.cine_number}:Width_RBV')
        self.cine_height = Cpt(EpicsSignalRO, f'C{self.cine_number}:Height_RBV')
        self.cine_frame_count = Cpt(EpicsSignalRO, f'C{self.cine_number}:FrameCount_RBV')
        self.cine_first_frame = Cpt(EpicsSignalRO, f'C{self.cine_number}:FirstFrame_RBV')
        self.cine_last_frame = Cpt(EpicsSignalRO, f'C{self.cine_number}:LastFrame_RBV')
        self.cine_record_start = Cpt(EpicsSignalRO, f'C{self.cine_number}:RecordStart_RBV')
        self.cine_record_end = Cpt(EpicsSignalRO, f'C{self.cine_number}:RecordEnd_RBV')
        self.cine_record_count = Cpt(EpicsSignalRO, f'C{self.cine_number}:RecordCount_RBV')
        self.cine_state_raw = Cpt(EpicsSignal, f'C{self.cine_number}:StateRaw')
        self.cine_state = Cpt(EpicsSignalRO, f'C{self.cine_number}:State_RBV')

class ADPhantomReadoutStatus(DeviceStatus):

    """
    A Status for ADPhantomReadout triggers

    A special status object that notifies watches (progress bars)
    based on comparing record count vs. span of record start to record end.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_ts = ttime.time()


        # Notify watchers (things like progress bars) of new values
        # at the device's natural update rate.
        if not self.done:
            self.device.record_count.subscribe(self._notify_watchers)
            # some state needed only by self._notify_watchers
            self._name = self.device.name
            self._initial_count = self.device.record_count.get()
            self._target_count = self.device.record_end.get() - self.device.record_start.get()

    def watch(self, func):
        self._watchers.append(func)

    def _notify_watchers(self, value, *args, **kwargs):
        # *args and **kwargs catch extra inputs from pyepics, not needed here
        if self.done:
            self.device.record_count.clear_sub(self._notify_watchers)
        if not self._watchers:
            return
        # Always start progress bar at 0 regardless of starting value of
        # array_counter.
        current = value - self._initial_count
        target = self._target_count
        initial = 0
        time_elapsed = ttime.time() - self.start_ts
        try:
            fraction = 1 - (current - initial) / (target - initial)
        except ZeroDivisionError:
            fraction = 0
        except Exception:
            fraction = None
            time_remaining = None
        else:
            time_remaining = time_elapsed / fraction
        for watcher in self._watchers:
            watcher(
                name=self._name,
                current=current,
                initial=initial,
                target=target,
                unit="images",
                precision=0,
                fraction=fraction,
                time_elapsed=time_elapsed,
                time_remaining=time_remaining,
            )


class ADPhantomCollect(CamBase):
    """
    Data acquisition via the Phantom VEO camera is done in four steps.

    First, the detector is armed and begins collecting data in it's internal ring buffer.
    This is done by writing `1` to the traditional areaDetector `Acquire` PV.

    Next, the detector will wait for an event trigger. This can either be a 5V TTL on the BNC connector,
    or a software based even trigger can be used by writing `1` to the `SendSoftwareTrigger PV.

    Once it recieves the trigger, the camera will collect a further predefined number of frames, and then stop.

    This class is responsible for handling these two steps of the acquisition.

    """
    acq_notify = Cpt(EpicsSignal, 'AcqNotify')
    partition_cines = Cpt(EpicsSignal, 'PartitionCines')
    cine_count = Cpt(EpicsSignalRO, 'CineCount_RBV')
    max_frame_count = Cpt(EpicsSignalRO, 'MaxFrameCount_RBV')
    post_trig_frames = Cpt(SignalWithRBV, 'PostTrigFrames')
    total_frame_count = Cpt(EpicsSignalRO, 'TotalFrameCount_RBV')
    auto_save = Cpt(SignalWithRBV, 'AutoSave')
    auto_restart = Cpt(SignalWithRBV, 'AutoRestart')
    auto_bref = Cpt(SignalWithRBV, 'AutoBref')
    cine_name = Cpt(SignalWithRBV, 'CineName')
    selected_cine = Cpt(SignalWithRBV, 'SelectedCine')
    ext_sync_type = Cpt(SignalWithRBV, 'ExtSyncType')
    complete_and_valid = Cpt(EpicsSignalRO, 'State_RBV.B1')
    waiting_for_trigger = Cpt(EpicsSignalRO, 'State_RBV.B2')
    trigger_recieved = Cpt(EpicsSignalRO, 'State_RBV.B3')
    
    def stage(self):
        super.stage()

    def unstage(self):
        super().unstage()

    
    def trigger(self):
        
        def check_recieved_event_trigger(value, old_value, **kwargs):
            if value == 1 and old_value == 0:
                print('Event trigger detected...')
                return True
            return False

        # Start acquisition
        self.acquire.put(1)
        print('Waiting for event trigger...')
    
        # Create subscription status to wait until we recieve an external event trigger signal
        wait_for_trigger_status = SubscriptionStatus(self.trigger_recieved, run=False, callback=check_recieved_event_trigger)
        wait_for_trigger_status.wait()

        def check_post_frame_count_done(value, old_value, **kwargs):
            # Print our current post trigger frame count
            if value > 0:
                print(f'Collected {value} frames after event trigger...')
            
            # If we hit the number of post trigger frames we wanted, we are done.
            if value == self.post_trig_frames.get() and self.complete_and_valid.get() == 1:
                print('Collected all requested post-event-trigger frames...')
                return True
            return False

        status = SubscriptionStatus(self.array_counter, run=False, callback=check_post_frame_count_done)

        return status 


class ADPhantomReadout(Device):

    cine_frame_count = Cpt(EpicsSignalRO, 'CineFrameCount_RBV')
    cine_first_frame = Cpt(EpicsSignalRO, 'CineFirstFrame_RBV')
    cine_last_frame = Cpt(EpicsSignalRO, 'CineLastFrame_RBV')
    record_start = Cpt(SignalWithRBV, 'RecordStart')
    record_end = Cpt(SignalWithRBV, 'RecordEnd')
    record = Cpt(EpicsSignal, 'Record')
    record_count = Cpt(EpicsSignalRO, 'RecordCount_RBV')
    state_raw = Cpt(EpicsSignal, 'StateRaw')
    state = Cpt(EpicsSignalRO, 'State_RBV')
    send_software_trigger = Cpt(EpicsSignal, 'SendSoftwareTrigger')
    perform_csr = Cpt(EpicsSignal, 'PerformCSR')
    csr_count = Cpt(EpicsSignalRO, 'CSRCount_RBV')
    preview = Cpt(SignalWithRBV, 'Preview')
    sensor_temp = Cpt(EpicsSignalRO, 'SensorTemp_RBV')
    thermo_power = Cpt(EpicsSignalRO, 'ThermoPower_RBV')
    camera_temp = Cpt(EpicsSignalRO, 'CameraTemp_RBV')
    fan_power = Cpt(EpicsSignalRO, 'FanPower_RBV')
    
    edr = Cpt(SignalWithRBV, 'EDR')
    frame_delay = Cpt(SignalWithRBV, 'FrameDelay')
    trigger_edge = Cpt(SignalWithRBV, 'TriggerEdge')
    trigger_filter = Cpt(SignalWithRBV, 'TriggerFilter')
    ready_signal = Cpt(SignalWithRBV, 'ReadySignal')
    aux_pin_mode = Cpt(SignalWithRBV, 'AuxPinMode')
    sync_clock = Cpt(EpicsSignal, 'SyncClock')
    acquire_time = Cpt(EpicsSignal, 'AcquireTime')
    acquire_period = Cpt(EpicsSignal, 'AcquirePeriod')
    data_type = Cpt(SignalWithRBV, 'DataType')
    color_mode = Cpt(SignalWithRBV, 'ColorMode')
    bin_x = Cpt(SignalWithRBV, 'BinX')
    bin_y = Cpt(SignalWithRBV, 'BinY')
    min_x = Cpt(SignalWithRBV, 'MinX')
    min_y = Cpt(SignalWithRBV, 'MinY')
    gain = Cpt(SignalWithRBV, 'Gain')
    reverse_x = Cpt(EpicsSignal, 'ReverseX')
    reverse_y = Cpt(EpicsSignal, 'ReverseY')
    connected = Cpt(EpicsSignalRO, 'CONNECTED_RBV')



    hdf5_plugin = Cpt(HDF5PluginWithFileStore, 
                      suffix='HDF1:',
                      root='/',
                      write_path_template=f'/nsls2/data/tst/legacy/mock-proposals/2024-1/pass-000000/VEO/%Y/%m/%d')


    def trigger(self):

        self.record.put(1)
        ttime.sleep(0.1)

        status = ADPhantomReadoutStatus(self)

        return status

    #def __init__(self, *args, num_cines=1, **kwargs):
    #    for n in num_cines:
    #        self.

class ADPhantom(Device):


    collect_interface = Cpt(ADPhantomCollect, 'cam1:')
    readout_interface = Cpt(ADPhantomReadout, 'cam1:')



    def trigger_collect_interface_sw(self, post_trigger_frames):
        yield from bps.mv(self.collect_interface.ext_sync_type, 'FREE-RUN')
        yield from bps.mv(self.collect_interface.post_trig_frames, post_trigger_frames)
        yield from bps.trigger(self.collect_interface, wait=True)


    def trigger_collect_interface_hw(self, post_trigger_frames):
        yield from bps.mv(self.collect_interface.ext_sync_type, 'FSYNC')
        yield from bps.mv(self.collect_interface.post_trig_frames, post_trigger_frames)
        yield from bps.trigger(self.collect_interface, wait=True)



phantom_veo = ADPhantom('XF:31ID1-ES{Det:VEO-1}', name= 'phantom_veo')



def phantom_base_scan_hdf5(det, pre_trigger_frames, post_trigger_frames, trigger_mode='sw'):

    if post_trigger_frames < 1:
        print('Number of post event trigger frames cannot be less than 1! Defaulting to 1.')
        post_trigger_frames = 1

    base_collect_trigger_func = getattr(det, f'trigger_collect_interface_{trigger_mode}')

    yield from base_collect_trigger_func(post_trigger_frames)

    print('Beginning readout from detector ring buffer...')
    yield from bps.mv(det.readout_interface.record_start, -1 * pre_trigger_frames)
    yield from bps.mv(det.readout_interface.record_end, post_trigger_frames - 1)
    yield from bps.trigger(det.readout_interface, wait=True)
