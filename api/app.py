import falcon
import json
from os import path, getcwd
from api import SRT
from api import Inputs
from api import Outputs
from api import StreamControls
from api import AudioControls
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


pipelines, pipelines_meta, srt_passphrase = control.setup()

srt_watcher_thread = SRTThread(passphrase=srt_passphrase, srt_destination=pipelines["output1"].url)
srt_watcher_thread.daemon = True
srt_watcher_thread.start()

srt_stats = SRT(srt=srt_watcher_thread)
input_status = Inputs(pipelines["input1"], pipelines["input2"], pipelines["output1"])
output_status = Outputs(pipelines["output1"])
remote_controls = control.StreamRemoteControl()
stream_controls = StreamControls(remote_controls)
audio_controls = AudioControls(pipelines["output1"])

bitrate_watcher_thread = control.BitrateWatcherThread(output_status, srt_watcher_thread)
bitrate_watcher_thread.daemon = True
bitrate_watcher_thread.start()

api.add_static_route("/static", path.join(getcwd(), "frontend"), fallback_filename='index.html')
api.add_route("/srt-stats", srt_stats)
api.add_route("/inputs/{input_name}", input_status)
api.add_route("/inputs", input_status)
api.add_route("/outputs", output_status)
api.add_route("/outputs/encoder/{bitrate}", output_status)
api.add_route("/stream/start", stream_controls)
api.add_route("/stream/stop", stream_controls)
api.add_route("/stream/brb", stream_controls)
api.add_route("/stream/back", stream_controls)
api.add_route("/stream/status", stream_controls)
api.add_route("/audio/", audio_controls)
api.add_route("/audio/mute", audio_controls, suffix="mute")
api.add_route("/audio/{input_name}", audio_controls, suffix="name")