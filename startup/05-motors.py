print(f"Loading file {__file__!r} ...")

from ophyd import Component as Cpt
from ophyd import EpicsMotor, EpicsSignal


class EpicsMotorWithSPMG(EpicsMotor):
    spmg = Cpt(EpicsSignal, ".SPMG")
    velocity = Cpt(EpicsSignal, ".VELO")


rot_motor = EpicsMotorWithSPMG("XF:31ID1-OP:1{CMT:1-Ax:X}Mtr", name="rot_motor")
