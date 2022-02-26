import falcon
import json
import srt_obs_switcher as srtos
from datetime import datetime
import logging as lg
from loguru import logger as logging
from utils import configure_logging, generate_api_key
import threading

class StreamControls:
    def __init__(self, cfg, api_key, websocket=None):
        api_config = cfg["api"]
        self.api_key = api_key
        self.key_len = 32
        self.last_hearbeat = None
        self.obs_websoc = websocket
        self.time_str = "%Y-%m-%dT%H:%M:%S.%fZ"
        div = "--------------------------------------------"
        print(f"\nAPI Key:")
        print(div)
        print(f"{self.api_key}")
        print(div)   

    def nice_hearbeat(self):
        return datetime.strftime(self.last_hearbeat, self.time_str)

    def on_get_heartbeat(self, req, res):
        self.last_hearbeat = datetime.now()
        j = {"heartbeat": self.nice_hearbeat()}
        logging.debug("Control: heartbeat")
        res.text = json.dumps(j)
        res.status = falcon.HTTP_200

    def on_get(self, req, res):
        logging.debug("Control: stats get")
        status = self.obs_websoc.stream_status()
        curr_scene = self.obs_websoc.get_current_scene()
        j = {"streaming": status.getStreaming(),
            "recording": status.getRecording(),
            "scene": curr_scene,
            "locked": self.obs_websoc.scene_locked,}

        res.text = json.dumps(j)
        res.status = falcon.HTTP_200

    def on_post_start(self, req, res):
        res = self.obs_websoc.start_stream()
        logging.debug(f"Controls: start: {res}")
        if res:
            j = {"message": "Stream started."}
            logging.info(f"Controls: Stream started.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error starting stream."}
            logging.critical(f"Controls: Stream start failed.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_stop(self, req, res):
        res = self.obs_websoc.stop_stream()
        logging.debug(f"Controls: stop: {res}")
        if res:
            j = {"message": "Stream stopped."}
            logging.info(f"Controls: Stream stopped.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error stopping stream."}
            logging.critical(f"Controls: Stream stop failed.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_brb(self, req, res):
        res = self.obs_websoc.go_brb(locked=True)
        logging.debug(f"Controls: brb: {res}")
        if res:
            j = {"message": "Going brb."}
            logging.info(f"Controls: Stream brb.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error going brb."}
            logging.critical(f"Controls: Stream brb failed.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_back(self, req, res):
        res = self.obs_websoc.go_normal(locked=True)
        logging.debug(f"Controls: back: {res}")
        if res:
            j = {"message": "Going normal."}
            logging.info(f"Controls: Stream back.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_200
        else:
            j = {"message": "Error going normal."}
            logging.critical(f"Controls: Stream back failed.")
            res.text = json.dumps(j)
            res.status = falcon.HTTP_409

    def on_post_unlock(self, req, res):
        self.obs_websoc.scene_locked = False
        j = {"message": "Scene unlocked."}
        logging.debug(f"Controls: Scene Unlocked.")
        res.text = json.dumps(j)
        res.status = falcon.HTTP_200


class KeyMiddleware(object):
    def __init__(self, api_key):
        self.api_key = api_key

    def process_request(self, req, res):
        key = req.get_header('X-API-Key')
        if key != self.api_key:
            err = json.dumps({"message": "API key required"})
            raise falcon.HTTPUnauthorized(err)

config = srtos.get_config()

# Configure logging first, before doing anything else.
configure_logging(log_level=config["logging"]["log_level"])

api_key = generate_api_key(config)

key_check = KeyMiddleware(api_key)
api = application = falcon.App(middleware=[key_check])
obs_websoc = srtos.OBSWebsocket(config)

srt_thread = srtos.start_srt(config)
srtla_thread = srtos.start_srtla(config)

obs_ctrl = srtos.OBSControl(srt_thread=srt_thread, websocket=obs_websoc)
obs_ctrl.daemon = True
obs_ctrl.start()

stream_controls = StreamControls(cfg=config, api_key=api_key, websocket=srtos.OBSWebsocket(config))

api.add_route("/heartbeat", stream_controls, suffix="heartbeat")
api.add_route("/start", stream_controls, suffix="start")
api.add_route("/stop", stream_controls, suffix="stop")
api.add_route("/brb", stream_controls, suffix="brb")
api.add_route("/back", stream_controls, suffix="back")
api.add_route("/unlock", stream_controls, suffix="unlock")
api.add_route("/status", stream_controls)
api.add_route("/", stream_controls)

for thread in threading.enumerate():
    logging.debug(f"thread: {thread}.")

def on_exit(arbiter):
    obs_websoc.go_brb()
    obs_websoc.disconnect()
    logging.info("Shutting down.")
    logging.info(f"SRT Thread start: {srt_thread.start_time}")
    logging.info(f"SRTLA Thread start: {srtla_thread.start_time}")
    logging.info(f"OBS control Thread start: {obs_ctrl.start_time}")
    srt_thread.stop()
    srtla_thread.stop()
    obs_ctrl.stop()