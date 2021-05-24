from srt_stats import SRTThread, SRTLAThread
import toml
from obswebsocket import obsws, requests
from dataclasses import dataclass
from time import sleep
from itertools import chain
import threading
from datetime import datetime, timedelta
from loguru import logger as logging


def get_config(config_file="srt_config.toml"):
    with open(config_file, 'r') as f:
        cfg = toml.load(f)
        logging.debug(f"Config file:\n\n{cfg}")
        return cfg

class OBSWebsocket(object):
    def __init__(self, obs_cfg):
        self.config = obs_cfg
        self.ws = None
        self.normal_scene = self.config["scene_name"]
        self.brb_scene = self.config["brb_scene_name"]
        self.scene_locked = False
        self.ws_connect()
        self.scenes = None
        self.get_scenes()

    def ws_connect(self):
        logging.debug("OBS Command: Attempting websocket connection.")
        ws_host = self.config["websocket_host"]
        ws_port = self.config["websocket_port"]
        ws_secret = self.config["websocket_secret"]
        self.ws = obsws(ws_host, ws_port, ws_secret)
        logging.debug(f"OBS command: connect. host: {ws_host}, port: {ws_port}, secret: {ws_secret}.")
        self.ws.connect()
        print("Websocket:", self.ws)

    def disconnect(self):
        logging.debug("OBS command: disconnect.")
        self.ws.disconnect()

    def get_scenes(self):
        logging.debug("OBS command: get all scenes.")
        self.scenes = self.ws.call(requests.GetSceneList())

    def go_brb(self, locked=False):
        logging.info("OBS command: switch to BRB scene.")
        if locked:
            self.scene_locked = True
        # self.media_source_toggle()
        return self.ws.call(requests.SetCurrentScene(self.brb_scene))

    def go_normal(self, locked=False):
        logging.info("OBS command: switch to normal scene.")
        if locked:
            self.scene_locked = False
        self.media_source_toggle()
        return self.ws.call(requests.SetCurrentScene(self.normal_scene))

    def start_stream(self):
        logging.info("OBS command: start stream.")
        return self.ws.call(requests.StartStreaming())

    def stop_stream(self):
        logging.info("OBS command: stop stream.")
        return self.ws.call(requests.StopStreaming())

    def stream_status(self):
        logging.debug("OBS command: get stream status.")
        return self.ws.call(requests.GetStreamingStatus())

    def get_current_scene(self):
        logging.debug("OBS command: get current scene.")
        s = self.ws.call(requests.GetCurrentScene())
        return s.getName()

    @property
    def current_scene(self):
        return self.ws.call(requests.GetCurrentScene()).getName()

    def get_media_sources(self):
        srcs = self.ws.call(requests.GetSourcesList()).getSources()
        media_src_types = ("vlc_source", "ffmpeg_source")
        media_sources = [x for x in srcs if x['typeId'] in media_src_types]
        logging.debug(f"OBS command: get media sources.\n{media_sources}")
        return media_sources

    @property
    def active_media_source(self, live_scene_name="IRL Input"):
        # This assumes that the only visible media source is active.
        srcs = self.get_media_sources()
        for s in srcs:
            k = s["name"]
            if self.ws.call(requests.GetSceneItemProperties(k, live_scene_name)).getVisible():
                return k

    def stop_media_source(self, source_name):
        logging.debug(f"OBS command: stop media source '{source_name}'.")
        return self.ws.call(requests.StopMedia(source_name))

    def play_media_source(self, source_name):
        logging.debug(f"OBS command: play media source '{source_name}'.")
        return self.ws.call(requests.PlayPauseMedia(source_name, "play"))

    def pause_media_source(self, source_name):
        logging.debug(f"OBS command: pause media source '{source_name}'.")
        return self.ws.call(requests.PlayPauseMedia(source_name, "pause"))

    def restart_active_source(self):
        active_src = self.active_media_source
        logging.warning(f"OBS command: twiddle media source '{active_src}'.")
        self.stop_media_source(active_src)
        self.play_media_source(active_src)


    def media_source_toggle(self):
        """
        This is a janky, awful hack, but for some reason OBS 26.1.1 seems to hit a black screen with the media source and not recover.
        Stopping/playing, pausing/playing, toggling visibility don't do anything.
        The _only_ way to get it to come back reliably seems to be to change a setting in the dialog.
        Seekable doesn't seem to affect things, so the hack is to toggle it.
        """
        active_src = self.active_media_source
        src_settings = self.ws.call(requests.GetSourceSettings(active_src)).getSourceSettings()
        if "seekable" not in src_settings:
            logging.warning(f"OBS command: toggle failed, {active_src} not a Media Source.")
        else:
            s = src_settings["seekable"]
            logging.warning(f"OBS command: toggle {active_src} from {s} to {not s}.")
            self.ws.call(requests.SetSourceSettings(active_src, {"seekable": not s}))

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
        self.connected = False
        #  5 added because it seemed too short otherwise. This seems like a hack...
        self.update_timeout = timedelta(seconds=self.stabilize_dec * self.ra_samples * 5)
        self.cooldown_timeout = timedelta(seconds=self.thresholds["cooldown_time"])
        self.cooldown_timer = datetime.now()
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
            logging.debug(f"Current scene: {current_scene}, countdown: {stabilize_countdown}.")
            stats = self.srt_thread.last_stats
            timestamp = datetime.now()

            # Want to track connection.
            if "Accepted SRT source connection" in self.srt_thread.last_message and not self.connected:
                logging.info(f"SRT: Source Connected.")
                self.connected = True

            if stats != {}:
                rtt_samples[idx % self.ra_samples] = stats["link"]["rtt"]
                # This is a workaround for not always getting the same stats.
                bitrate_samples[idx % self.ra_samples] = max(stats["send"]["mbitRate"], stats['recv']['mbitRate'])
                logging.info(f"{stats['send']['mbitRate']}, {stats['recv']['mbitRate']}")
                rtt_ra = sum([x for x in rtt_samples if not x in (None, 0)]) / self.ra_samples
                bitrate_ra = sum([x for x in bitrate_samples if not x in (None, 0)]) / self.ra_samples
                # pure stats based health determination
                rtt_healthy = rtt_ra <= self.thresholds["rtt"]
                bitrate_healthy = bitrate_ra >= self.thresholds["bitrate"]
                healthy = rtt_healthy and bitrate_healthy
                if not healthy:
                    logging.warning(f"SRT: Failed health check. RTT: {rtt_healthy}, bitrate: {bitrate_healthy}.")
            else:
                logging.info(f"SRT stats blank.")

            # If the source disconnects due to a drop withou explicitly disconnecting, we should go brb.
            # This is explicitly needed because the stats don't update in this case, so the code never sees the bitrate disappear.
            # We should only complain about a failure to update stats when the source is connected. There may be an edge case here.
            last_update_delta = timestamp - self.srt_thread.last_update
            if last_update_delta >= self.update_timeout and self.connected:
                logging.warning(f"SRT: Stats have not been updated for: {last_update_delta}, which is longer than cutoff: {self.update_timeout}.")
                healthy = False

            # If the remote disconnects explicitly, go BRB.
            # To do this we parse the message from the SRT messages.
            if "SRT source disconnected" in self.srt_thread.last_message and self.connected:
                self.connected = False
                logging.info(f"SRT: Source Disconnected.")
                healthy = False

            if stats != {}:
                logging.debug(f"rtt: {rtt_ra}, bitrate: {bitrate_ra}, healthy: {healthy}, locked: {self.obs_websoc.scene_locked}, connected: {self.connected}.")
                logging.debug(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}, update delta: {last_update_delta}.")
            else:
                logging.debug(f"No stats. Healthy: {healthy}, locked: {self.obs_websoc.scene_locked}, connected: {self.connected}.")
                logging.debug(f"rtt hist: {rtt_samples}, bitrate hist: {bitrate_samples}, update delta: {last_update_delta}.")

            if not self.obs_websoc.scene_locked and not self.connected:
                healthy = False


            # If scene has been manually locked, don't switch scenes, even if we otherwise should.
            if self.obs_websoc.scene_locked:
                pass
            elif healthy:
                if stabilize_countdown >= 0.0:
                    stabilize_countdown -= self.stabilize_dec
                    logging.debug(f"SRT: in stabilization countdown. {stabilize_countdown}")
                elif current_scene == self.brb_scene and stabilize_countdown <= 0.0:
                    logging.debug(f"SRT: stabilization countdown finished")
                    self.obs_websoc.go_normal()
            elif current_scene != self.brb_scene:
                logging.info(f"{timestamp}, {self.cooldown_timer}")
                if timestamp > self.cooldown_timer:
                    logging.debug(f"SRT: Switching to BRB scene.")
                    self.obs_websoc.go_brb()
                    stabilize_countdown = self.thresholds["stabilize_time"]
                    self.cooldown_timer = datetime.now() + self.cooldown_timeout
                else:
                    logging.info(f"BRB triggered, but on cooldown for {timestamp - self.cooldown_timeout}.")
            else:
                logging.debug(f"SRT: starting stabilization countdown {stabilize_countdown}")
                stabilize_countdown = self.thresholds["stabilize_time"]

            logging.debug(f"SRT: next update in {self.thresholds['check_interval']}s")
            self.event.wait(self.thresholds["check_interval"])

    def stop(self):
        logging.debug("SRT: stop triggered")
        self.event.set()


def start_srt(config):
    srt_cfg = config["srt_relay"]
    srt_passphrase = srt_cfg["encryption_passphrase"]
    srt_thread = SRTThread(
        srt_destination=f"srt://:{srt_cfg['output_port']}",
        srt_source=f"srt://localhost:4001",
        passphrase=srt_passphrase,
        srt_live_transmit=srt_cfg['srtla_slt_path'],
        loss_max_ttl=srt_cfg['srt_latency'],
        srt_latency=srt_cfg['loss_max_ssl'],)
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
