import falcon
import json
from os import path, getcwd
from time import sleep
import srt_obs_switcher as srtos
import secrets
from datetime import datetime


class StreamControls(object):
    def __init__(self, obs_ctrl, config_file="srt_config.toml"):
        api_config = srtos.get_config(config_file)["api"]
        self.listen = api_config["listen"]
        self.api_key = api_config["api_key"]
        self.key_len = 32
        self.last_hearbeat = None
        self.obs_ctrl = obs_ctrl
        self.obs_websoc = obs_ctrl.obs_websoc
        self.time_str = "%Y-%m-%dT%H:%M:%S.%fZ"
        if not self.api_key:
            self.generate_key()
        div = "--------------------------------------------"
        print(f"\nAPI Key:")
        print(div)
        print(f"{self.api_key}")
        print(div)

    def generate_key(self):
        self.api_key = secrets.token_urlsafe(self.key_len)

    def nice_hearbeat(self):
        return datetime.strftime(self.last_hearbeat, self.time_str)


    def on_get_heartbeat(self, req, res):
        self.last_hearbeat = datetime.now()
        j = {"heartbeat": self.nice_hearbeat()}
        res.body = json.dumps(j)
        res.status = falcon.HTTP_200

    def on_get(self, req, res):
        status = self.obs_websoc.stream_status()
        curr_scene = self.obs_websoc.get_current_scene()
        j = {"streaming": status.getStreaming(), "recording": status.getRecording(), "scene": curr_scene}
        res.body = json.dumps(j)
        res.status = falcon.HTTP_200

    def on_post_start(self, req, res):
        res = self.obs_websoc.start_stream()
        print(res)
        print("Stream started.")
        if res:
            j = {"message": "Stream started."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error starting stream."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_stop(self, req, res):
        res = self.obs_websoc.stop_stream()
        print(res)
        print("Stream stopped.")
        if res:
            j = {"message": "Stream stopped."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error stopping stream."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_brb(self, req, res):
        res = self.obs_websoc.go_brb(manual=True)
        print(res)
        print("Stream brb.")
        if res:
            j = {"message": "Going brb."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error going brb."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_back(self, req, res):
        res = self.obs_websoc.go_normal(manual=True)
        print(res)
        print("Stream back.")
        if res:
            j = {"message": "Going normal."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error going normal."}
            res.body = json.dumps(j)
            res.status = falcon.HTTP_409

class KeyMiddleware(object):
    def __init__(self, api_key):
        self.api_key = api_key

    def process_request(self, req, res):
        key = req.get_header('X-API-Key')
        if key != self.api_key:
            err = json.dumps({"message": "API key required"})
            raise falcon.HTTPUnauthorized(err)

config = srtos.get_config()
srt_thread = srtos.start_srt(config)
srtla_thread = srtos.start_srtla(config)
debug = False

obs_ctrl = srtos.OBSControl(srt_thread=srt_thread, debug=debug)
obs_ctrl.daemon = True
obs_ctrl.start()

stream_controls = StreamControls(obs_ctrl)
key_check = KeyMiddleware(stream_controls.api_key)
api = application = falcon.API(middleware=[key_check])
api.add_route("/heartbeat", stream_controls, suffix="heartbeat")
api.add_route("/start", stream_controls, suffix="start")
api.add_route("/stop", stream_controls, suffix="stop")
api.add_route("/brb", stream_controls, suffix="brb")
api.add_route("/back", stream_controls, suffix="back")
api.add_route("/status", stream_controls)
api.add_route("/", stream_controls)