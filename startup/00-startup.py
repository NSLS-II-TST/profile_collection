# Make ophyd listen to pyepics.
print(f"Loading file {__file__!r} ...")

import asyncio
import datetime
import logging
import os
import subprocess
import warnings

import epicscorelibs.path.pyepics
import nslsii
import ophyd.signal
from bluesky.callbacks.broker import post_run, verify_files_saved
from bluesky.callbacks.tiled_writer import TiledWriter
from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop
from databroker.v0 import Broker
from IPython import get_ipython
from tiled.client import from_uri

ophyd.signal.EpicsSignal.set_defaults(connection_timeout=5)
# See docstring for nslsii.configure_base() for more details
# this command takes away much of the boilerplate for setting up a profile
# (such as setting up best-effort callback, etc)


nslsii.configure_base(
    get_ipython().user_ns,
    Broker.named("temp"),
    pbar=True,
    bec=True,
    magics=True,
    mpl=True,
    epics_context=False,
)

event_loop = asyncio.get_event_loop()
RE = RunEngine(loop=event_loop)
RE.subscribe(bec)

tiled_client = from_uri("http://localhost:8000", api_key=os.getenv("TILED_API_KEY", ""))
tw = TiledWriter(tiled_client)
RE.subscribe(tw)

# This is needed for ophyd-async to enable 'await <>' instead of 'asyncio.run(<>)':
get_ipython().run_line_magic("autoawait", "call_in_bluesky_event_loop")

# PandA does not produce any data for plots for now.
bec.disable_plots()
bec.disable_table()

# At the end of every run, verify that files were saved and
# print a confirmation message.
# RE.subscribe(post_run(verify_files_saved, db), 'stop')

# Uncomment the following lines to turn on verbose messages for
# debugging.
# ophyd.logger.setLevel(logging.DEBUG)
# logging.basicConfig(level=logging.DEBUG)


RE.md["facility"] = "NSLS-II"
RE.md["group"] = "TST"
RE.md["beamline_id"] = "31-ID-1"


warnings.filterwarnings("ignore")


def show_env():
    # this is not guaranteed to work as you can start IPython without hacking
    # the path via activate
    proc = subprocess.Popen(["conda", "list"], stdout=subprocess.PIPE)
    out, err = proc.communicate()
    a = out.decode("utf-8")
    b = a.split("\n")
    print(b[0].split("/")[-1][:-1])


PROPOSAL_DIR = "/nsls2/data/tst/legacy/mock-proposals/2024-1/pass-000000"
