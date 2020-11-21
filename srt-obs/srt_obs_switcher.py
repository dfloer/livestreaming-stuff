from srt_stats import SRTThread
import toml
from obswebsocket import obsws, requests
from dataclasses import dataclass
from time import sleep
from itertools import chain


def get_config(config_file="srt_config.toml"):
    with open(config_file, 'r') as f:
        return toml.load(f)

class OBSWebsocket(object):
    def __init__(self, obs_cfg):
        self.config = obs_cfg
        self.ws = None
        self.normal_scene = self.config["scene_name"]
        self.brb_scene = self.config["brb_scene_name"]
        self.manual_brb = False
        self.connect()
        self.scenes = None
        self.get_scenes()

    def connect(self):
        self.ws = obsws(self.config["websocket_host"], self.config["websocket_port"], self.config["websocket_secret"])
        self.ws.connect()

    def disconnect(self):
        self.ws.disconnect()

    def get_scenes(self):
        self.scenes = self.ws.call(requests.GetSceneList())

    def go_brb(self, manual=False):
        print("brb")
        if manual:
            self.manual_brb = True
        return self.ws.call(requests.SetCurrentScene(self.brb_scene))

    def go_normal(self, manual=False):
        print("normal")
        if manual:
            self.manual_brb = False
        return self.ws.call(requests.SetCurrentScene(self.normal_scene))

    def start_stream(self):
        print("starting stream")
        return self.ws.call(requests.StartStreaming())

    def stop_stream(self):
        print("stopping stream")
        return self.ws.call(requests.StartStreaming())

    def stream_status(self):
        return self.ws.call(requests.GetStreamingStatus())

    @property
    def current_scene(self):
        return self.ws.call(requests.GetCurrentScene()).getName()

    def __str__(self):
        return f"Scenes: {self.scenes}, normal name: {self.normal_scene}, brb name: {self.brb_scene}."


class OBSControl(object):
    def __init__(self, srt_thread, config_path="srt_config.toml"):
        self.config = get_config(config_path)
        self.srt_cfg = self.config["srt_relay"]
        self.srt_thread = srt_thread
        self.obs_cfg = self.config["obs"]
        self.thresholds = self.config["brb_thresholds"]
        self.brb_scene = self.obs_cfg["brb_scene_name"]
        self.stabilize_dec = self.thresholds["check_interval"]
        self.obs_websoc = OBSWebsocket(self.obs_cfg)
        # Make sure we're on our live scene.
        self.obs_websoc.go_normal()

    def run(self):
        ra_samples = self.thresholds["running_avg"]
        rtt_samples = [None for _ in range(ra_samples)]
        bitrate_samples = [None for _ in range(ra_samples)]
        stabilize_countdown = 0
        idx = 0
        while True:
            idx += 1
            current_scene = self.obs_websoc.current_scene
            print(f"Current scene: {current_scene}, countdown: {stabilize_countdown}.")
            stats = self.srt_thread.last_stats
            if stats == {}:
                continue

            rtt_samples[idx % ra_samples] = stats["link"]["rtt"]
            bitrate_samples[idx % ra_samples] = stats["send"]["mbitRate"]
            rtt_ra = sum([x for x in rtt_samples if x is not None]) / ra_samples
            bitrate_ra = sum([x for x in bitrate_samples if x is not None]) / ra_samples

            healthy = rtt_ra <= self.thresholds["rtt"] and bitrate_ra >= self.thresholds["bitrate"]
            if "SRT source disconnected" in self.srt_thread.last_message:
                healthy = False
            print(f"rtt: {rtt_ra}, bitrate: {bitrate_ra}, healthy: {healthy}, manual: {self.obs_websoc.manual_brb}")
            print(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}.")

            # If scene has been set manually to BRB, don't switch away from the BRB scene.
            if self.obs_websoc.manual_brb:
                pass
            elif healthy:
                if stabilize_countdown >= 0.0:
                    stabilize_countdown -= self.stabilize_dec
                elif current_scene == self.brb_scene and stabilize_countdown <= 0.0:
                    self.obs_websoc.go_normal()
            elif current_scene != self.brb_scene:
                self.obs_websoc.go_brb()
                stabilize_countdown = self.thresholds["stabilize_time"]
            else:
                stabilize_countdown = self.thresholds["stabilize_time"]

            sleep(self.thresholds["check_interval"])


def start_srt(config):
    srt_cfg = config["srt_relay"]
    srt_thread = SRTThread(f"srt://:{srt_cfg['output_port']}", f"srt://:{srt_cfg['listen_port']}")
    srt_thread.daemon = True
    srt_thread.start()
    return srt_thread

if __name__ == "__main__":
    config = get_config()

    srt_thread = start_srt(config)

    obs_ctrl = OBSControl(srt_thread=srt_thread)
    try:
        obs_ctrl.run()
    except KeyboardInterrupt:
        pass

    obs_ctrl.obs_websoc.disconnect()
    srt_thread.stop()