from srt_stats import SRTThread, SRTLAThread
import toml
from obswebsocket import obsws, requests
from dataclasses import dataclass
from time import sleep
from itertools import chain
import threading
from datetime import datetime, timedelta


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
        return self.ws.call(requests.StopStreaming())

    def stream_status(self):
        return self.ws.call(requests.GetStreamingStatus())

    def get_current_scene(self):
        s = self.ws.call(requests.GetCurrentScene())
        return s.getName()

    @property
    def current_scene(self):
        return self.ws.call(requests.GetCurrentScene()).getName()

    def __str__(self):
        return f"Scenes: {self.scenes}, normal name: {self.normal_scene}, brb name: {self.brb_scene}."


class OBSControl(threading.Thread):
    def __init__(self, srt_thread, config_path="srt_config.toml", debug=False):
        self.event = threading.Event()
        self.config = get_config(config_path)
        self.srt_cfg = self.config["srt_relay"]
        self.srt_thread = srt_thread
        self.obs_cfg = self.config["obs"]
        self.thresholds = self.config["brb_thresholds"]
        self.brb_scene = self.obs_cfg["brb_scene_name"]
        self.stabilize_dec = self.thresholds["check_interval"]
        self.obs_websoc = OBSWebsocket(self.obs_cfg)
        self.debug = debug
        self.ra_samples = self.thresholds["running_avg"]
        #  5 added because it seemed too short otherwise. This seems like a hack...
        self.update_timeout = timedelta(seconds=self.stabilize_dec * self.ra_samples * 5)
        # Make sure we're on our live scene.
        self.obs_websoc.go_normal()
        super().__init__(group=None)

    def run(self):
        rtt_samples = [None for _ in range(self.ra_samples)]
        bitrate_samples = [None for _ in range(self.ra_samples)]
        stabilize_countdown = 0
        idx = 0
        healthy = False
        while not self.event.is_set():
            idx += 1
            current_scene = self.obs_websoc.current_scene
            if self.debug:
                print(f"Current scene: {current_scene}, countdown: {stabilize_countdown}.")
            stats = self.srt_thread.last_stats
            timestamp = datetime.now()
            if stats != {}:
                rtt_samples[idx % self.ra_samples] = stats["link"]["rtt"]
                bitrate_samples[idx % self.ra_samples] = stats["send"]["mbitRate"]
                rtt_ra = sum([x for x in rtt_samples if x is not None]) / self.ra_samples
                bitrate_ra = sum([x for x in bitrate_samples if x is not None]) / self.ra_samples
                # pure stats based health determination
                healthy = rtt_ra <= self.thresholds["rtt"] and bitrate_ra >= self.thresholds["bitrate"]

            # If the source disconnects due to a drop withou explicitly disconnecting, we should go brb.
            # This is explicitly needed because the stats don't update in this case, so the code never sees the bitrate disappear.
            last_update_delta = timestamp - self.srt_thread.last_update
            if last_update_delta >= self.update_timeout:
                if self.debug:
                    print(f"Stats have not been updated for: {last_update_delta}, which is longer than cutoff: {self.update_timeout}.")
                healthy = False

            # If the remote disconnects explicitly, go BRB.
            # To do this we parse the message from the SRT messages.
            if "SRT source disconnected" in self.srt_thread.last_message:
                healthy = False
            if self.debug and stats != {}:
                print(f"rtt: {rtt_ra}, bitrate: {bitrate_ra}, healthy: {healthy}, manual: {self.obs_websoc.manual_brb}")
                print(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}, update delta: {last_update_delta}.")
            elif self.debug:
                print(f"No stats. Healthy: {healthy}, manual: {self.obs_websoc.manual_brb}")
                print(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}, update delta: {last_update_delta}.")


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

            self.event.wait(self.thresholds["check_interval"])

    def stop(self):
        self.event.set()


def start_srt(config):
    srt_cfg = config["srt_relay"]
    srt_passphrase = srt_cfg["encryption_passphrase"]
    srt_thread = SRTThread(
        srt_destination=f"srt://:{srt_cfg['output_port']}",
        srt_source=f"srt://localhost:4001",
        passphrase=srt_passphrase,
        srt_live_transmit=srt_cfg['srtla_slt_path'])
    srt_thread.daemon = True
    srt_thread.start()
    return srt_thread

def start_srtla(config):
    srtla_cfg = config["srt_relay"]
    srtla_thread = SRTLAThread(
        srtla_cfg['srtla_rec_path'],
        srtla_cfg['listen_port'],
        "localhost",
        4001)
    srtla_thread.daemon = True
    srtla_thread.start()
    return srtla_thread


if __name__ == "__main__":
    config = get_config()

    srt_thread = start_srt(config)

    obs_ctrl = OBSControl(srt_thread=srt_thread)
    obs_ctrl.daemon = True
    obs_ctrl.start()
    try:
        # There's probably a better way to do this, but this keeps the program running until ctrl+c.
        while True:
            sleep(1)
    except KeyboardInterrupt:
        pass
    obs_ctrl.stop
    obs_ctrl.obs_websoc.disconnect()
    srt_thread.stop()
