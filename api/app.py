import falcon
import json
import re
from os import path, getcwd
from api import SRT, SRTLA
from api import Inputs
from api import Outputs
from api import StreamControls
from api import AudioControls
from api import StreamOutput
from time import sleep
import logging

from srt_stats import SRTThread, SRTLAThread
from helpers import srtla_ip_setup
import control

logging.basicConfig(
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S %z")

class StaticResource(object):
    """
    Simple Falcon class to serve the static files needed for the web interface.
    """
    def on_get(self, req, resp, filename):
        resp.status = falcon.HTTP_200
        resp.content_type = "text/html"
        fn = path.join("frontend", filename)
        logging.debug(f"Static: {fn}")
        with open(fn, 'r') as f:
            resp.body = f.read()

api = application = falcon.API()

pipelines, pipelines_meta, srt_passphrase = control.setup()

srt_watcher_thread = SRTThread(passphrase=srt_passphrase, srt_destination="srt://localhost:6000?mode=caller")
srt_watcher_thread.daemon = True
srt_watcher_thread.start()

srt_protocol, srt_hostname, srt_port = re.split('://|:', pipelines["output1"].url)

srtla_ips_path, srtla_ip_addrs = srtla_ip_setup()
logging.info(f"srtla ips: {srtla_ips_path}")

control.setup_source_routing(srtla_ip_addrs.keys(), debug=True)
control.set_clocks(debug=True)

srtla_thread = SRTLAThread(srtla_send="/home/bob/git/srtla/srtla_send", destination_host=srt_hostname, destination_port=srt_port, ip_file=srtla_ips_path)
srtla_thread.daemon = True
srtla_thread.start()

srt_stats = SRT(srt=srt_watcher_thread)
srtla_stats = SRTLA(srtla=srtla_thread)
input_status = Inputs(pipelines["input1"], pipelines["input2"], pipelines["output1"])
output_status = Outputs(pipelines["output1"])
remote_controls = control.StreamRemoteControl()
stream_controls = StreamControls(remote_controls)
audio_controls = AudioControls(pipelines["output1"])
output_controls = StreamOutput(pipelines["output1"])

bitrate_watcher_thread = control.BitrateWatcherThread(output_status, srt_watcher_thread)
bitrate_watcher_thread.daemon = True
bitrate_watcher_thread.start()

api.add_static_route("/static", path.join(getcwd(), "frontend"), fallback_filename='index.html')
api.add_route("/srt-stats", srt_stats)
api.add_route("/srtla-stats", srtla_stats)
api.add_route("/inputs/{input_name}", input_status)
api.add_route("/inputs", input_status)
api.add_route("/outputs/play", output_controls, suffix="play")
api.add_route("/outputs/pause", output_controls, suffix="pause")
api.add_route("/outputs", output_status)
api.add_route("/outputs/encoder/{bitrate}", output_status)
api.add_route("/stream/start", stream_controls)
api.add_route("/stream/stop", stream_controls)
api.add_route("/stream/brb", stream_controls)
api.add_route("/stream/back", stream_controls)
api.add_route("/stream/unlock", stream_controls)
api.add_route("/stream/status", stream_controls)
api.add_route("/audio/", audio_controls)
api.add_route("/audio/mute", audio_controls, suffix="mute")
api.add_route("/audio/{input_name}", audio_controls, suffix="name")