import falcon
import json
from os import path, getcwd
from api import SRT as srt_res
from api import Inputs as inp_res
from api import Outputs as out_res
from api import StreamControls as con_res
from time import sleep

from srt_stats import SRTThread
import control


class StaticResource(object):
    """
    Simple Falcon class to serve the static files needed for the web interface.
    """
    def on_get(self, req, resp, filename):
        resp.status = falcon.HTTP_200
        resp.content_type = "text/html"
        fn = path.join("frontend", filename)
        print(fn)
        with open(fn, 'r') as f:
            resp.body = f.read()

api = application = falcon.API()

pipelines, pipelines_meta = control.setup(debug=True)

srt_watcher_thread = SRTThread(srt_destination=pipelines["output1"].url)
srt_watcher_thread.daemon = True
srt_watcher_thread.start()

srt_stats = srt_res(srt=srt_watcher_thread)
input_status = inp_res(pipelines["input1"], pipelines["input2"], pipelines["output1"])
output_status = out_res(pipelines["output1"])
stream_controls = con_res(pipelines)

bitrate_watcher_thread = control.BitrateWatcherThread(output_status, srt_watcher_thread, debug=True)
bitrate_watcher_thread.daemon = True
bitrate_watcher_thread.start()

api.add_static_route("/static", path.join(getcwd(), "frontend"), fallback_filename='index.html')
api.add_route("/srt-stats", srt_stats)
api.add_route("/inputs/{input_name}", input_status)
api.add_route("/inputs", input_status)
api.add_route("/outputs", output_status)
api.add_route("/outputs/encoder/{bitrate}", output_status)
api.add_route("/start", stream_controls)
api.add_route("/stop", stream_controls)