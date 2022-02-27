import json
import logging as lg
import multiprocessing as mp
import threading
from datetime import datetime
from multiprocessing import Lock
from multiprocessing.managers import AcquirerProxy, BaseManager, DictProxy
from multiprocessing.queues import Queue as mpQueue

import falcon
from loguru import logger as logging

import srt_obs_switcher as srtos
from utils import configure_logging, generate_api_key


class StreamControls:
    def __init__(self, api_key, shared_state, websocket=None):
        self.api_key = api_key
        self.key_len = 32
        self.last_hearbeat = None
        self.shared_state = shared_state
        self.time_str = "%Y-%m-%dT%H:%M:%S.%fZ"
        div = "--------------------------------------------"
        print(f"\nAPI Key:")
        print(div)
        print(f"{self.api_key}")
        print(div)
        self.obs_websoc = websocket

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
            "locked": self.shared_state.get("scene_lock"),}

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
        res = self.obs_websoc.go_brb()
        # Explicitly lock, because that's how it behaved before.
        self.shared_state.put("scene_lock", True)
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
        res = self.obs_websoc.go_normal()
        # Explicitly unlock, because that's how it behaved before.
        self.shared_state.put("scene_lock", False)
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
        self.shared_state.put("scene_lock", False)
        j = {"message": "Scene unlocked."}
        logging.warning(f"Controls: Scene Unlocked.")
        res.text = json.dumps(j)
        res.status = falcon.HTTP_200

    def on_post_lock(self, req, res):
        self.shared_state.put("scene_lock", True)
        j = {"message": "Scene locked."}
        logging.warning(f"Controls: Scene locked.")
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


class LockQueue(mpQueue):
    def __init__(self, *args, **kwargs):
        ctx = mp.get_context()
        super().__init__(ctx=ctx, *args, **kwargs)
        self.lock = mp.Lock

    def get(self, *args, **kwargs):
        logging.error(f"LockQueue get({args}, {kwargs})")
        with self.lock():
            return super().get(self, *args, **kwargs)

    def put(self, *args, **kwargs):
        logging.error(f"LockQueue put({args}, {kwargs})")
        with self.lock():
            return super().put(self, *args, **kwargs)


class SharedState:
    """
    This needs some serious explanation.
    Basically, given Gunicorn's pre-fork model, there's no way to share any sort of state between processes.
    Not even mp.Queue or mp.Lock, because they are forked as well, so the forked process now has independent copies.
    This is full on IPC using network communication. Probably should be replaced with full async code at some point, but that may not help.

    Methods:
        Note: There is a shared lock protecting the calls, but use_lock=False will not lock the dict. This is hazardous, but may improve performance.

        get(key, optional_default): behaves like dict.get(key, optional_default)
        put(key, value): behaves like dict[key] = value. Not that nested values are not support, so a list or dict (etc.) will need to be updated in one go.
    """
    def __init__(self, host="localhost", port=42424, key="gunicorn-local"):
        self.host = host
        self.port = port
        self.key = key.encode("ascii")
        self.shared_dict, self.shared_lock = self._get_shared_state()

    def _get_shared_state(self):
        shared_dict = {"scene_lock": False}
        shared_lock = Lock()
        manager = BaseManager((self.host, self.port), self.key)
        manager.register("get_dict", lambda: shared_dict, DictProxy)
        manager.register("get_lock", lambda: shared_lock, AcquirerProxy)
        # Check and see if the process is running, and if it isn't start it.
        # Note that this will fail if there is another process on the system using the host:post combo.
        try:
            manager.connect()
        except ConnectionRefusedError:
            manager.get_server()
            manager.start()
        return manager.get_dict(), manager.get_lock()

    def get(self, dict_key, default=None, use_lock=True):
        if not use_lock:
            return self.shared_dict.get(dict_key, default)
        with self.shared_lock:
            return self.shared_dict.get(dict_key, default)

    def put(self, dict_key, value, use_lock=True):
        if not use_lock:
            self.shared_dict[dict_key] = value
        with self.shared_lock:
            self.shared_dict[dict_key] = value

config = srtos.get_config()

shared_state = SharedState()

# Configure logging first, before doing anything else.
configure_logging(log_level=config["logging"]["log_level"])

api_key = generate_api_key(config)

key_check = KeyMiddleware(api_key)
api = application = falcon.App(middleware=[key_check])
obs_websoc = srtos.OBSWebsocket(config)

srt_thread = srtos.start_srt(config)
srtla_thread = srtos.start_srtla(config)

obs_ctrl = srtos.OBSControl(srt_thread=srt_thread, websocket=obs_websoc, shared_state=shared_state)
obs_ctrl.daemon = True
obs_ctrl.start()

stream_controls = StreamControls(api_key=api_key, shared_state=shared_state, websocket=srtos.OBSWebsocket(config))

api.add_route("/heartbeat", stream_controls, suffix="heartbeat")
api.add_route("/start", stream_controls, suffix="start")
api.add_route("/stop", stream_controls, suffix="stop")
api.add_route("/brb", stream_controls, suffix="brb")
api.add_route("/back", stream_controls, suffix="back")
api.add_route("/unlock", stream_controls, suffix="unlock")
api.add_route("/lock", stream_controls, suffix="lock")
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
