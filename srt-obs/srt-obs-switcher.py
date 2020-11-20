from srt_stats import SRTThread
import toml
from obswebsocket import obsws, requests
from dataclasses import dataclass
from time import sleep
from itertools import chain


def get_config(config_file="srt_config.toml"):
    with open(config_file, 'r') as f:
        return toml.load(f)

class OBSControl(object):
    def __init__(self, obs_cfg):
        self.config = obs_cfg
        self.ws = None
        self.normal_scene = self.config["scene_name"]
        self.brb_scene = self.config["brb_scene_name"]
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

    def go_brb(self):
        print("brb")
        self.ws.call(requests.SetCurrentScene(self.brb_scene))

    def go_normal(self):
        print("normal")
        self.ws.call(requests.SetCurrentScene(self.normal_scene))

    @property
    def current_scene(self):
        return self.ws.call(requests.GetCurrentScene()).getName()

    def __str__(self):
        return f"Scenes: {self.scenes}, normal name: {self.normal_scene}, brb name: {self.brb_scene}."


if __name__ == "__main__":
    config = get_config()

    srt_cfg = config["srt_relay"]
    srt_thread = SRTThread(f"srt://:{srt_cfg['output_port']}", f"srt://:{srt_cfg['listen_port']}")

    srt_thread.daemon = True
    srt_thread.start()

    obs_cfg = config["obs"]
    thresholds = config["brb_thresholds"]

    obs_ctrl = OBSControl(obs_cfg)

    brb_scene = obs_cfg["brb_scene_name"]

    stabilize_dec = thresholds["check_interval"]
    stabilize_countdown = 0

    # Make sure we're on our live scene.
    obs_ctrl.go_normal()

    ra_samples = thresholds["running_avg"]
    rtt_samples = [None for _ in range(ra_samples)]
    bitrate_samples = [None for _ in range(ra_samples)]
    try:
        idx = 0
        while True:
            idx += 1
            current_scene = obs_ctrl.current_scene
            print(f"Current scene: {current_scene}, countdown: {stabilize_countdown}.")
            stats = srt_thread.last_stats
            if stats == {}:
                continue

            rtt_samples[idx % ra_samples] = stats["link"]["rtt"]
            bitrate_samples[idx % ra_samples] = stats["send"]["mbitRate"]
            rtt_ra = sum([x for x in rtt_samples if x is not None]) / ra_samples
            bitrate_ra = sum([x for x in bitrate_samples if x is not None]) / ra_samples

            healthy = rtt_ra <= thresholds["rtt"] and bitrate_ra >= thresholds["bitrate"]
            if "SRT source disconnected" in srt_thread.last_message:
                healthy = False
            print(f"rtt: {rtt_ra}, bitrate: {bitrate_ra}, healthy: {healthy}.")
            print(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}.")

            if healthy:
                if stabilize_countdown >= 0.0:
                    stabilize_countdown -= stabilize_dec
                elif current_scene == brb_scene and stabilize_countdown <= 0.0:
                    obs_ctrl.go_normal()
            elif current_scene != brb_scene:
                obs_ctrl.go_brb()
                stabilize_countdown = thresholds["stabilize_time"]
            else:
                stabilize_countdown = thresholds["stabilize_time"]

            sleep(thresholds["check_interval"])
    except KeyboardInterrupt:
        pass

    obs_ctrl.disconnect()
    srt_thread.stop()
