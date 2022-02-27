from srt_stats import SRTThread, SRTLAThread
import toml
from obswebsocket import obsws, requests
from dataclasses import dataclass
from time import sleep
from itertools import chain
import threading
from datetime import datetime, timedelta
from loguru import logger as logging
from utils import get_config, ThreadManager
import threading

class OBSWebsocket:
    def __init__(self, obs_cfg):
        self.config = obs_cfg["obs"]
        self.normal_scene = self.config["scene_name"]
        self.brb_scene = self.config["brb_scene_name"]
        self.ws = None
        self.scenes = None
        self.is_connected = False

    def ws_connect(self):
        logging.debug("OBS Command: Attempting websocket connection.")
        ws_host = self.config["websocket_host"]
        ws_port = self.config["websocket_port"]
        ws_secret = self.config["websocket_secret"]
        ws = obsws(ws_host, ws_port, ws_secret)
        logging.debug(f"OBS command: connect. host: {ws_host}, port: {ws_port}, secret: {ws_secret}.")
        ws.connect()
        logging.debug(f"OBS Command: Websocket successful: {ws}")
        return ws

    def ws_call(self, *args, **kwargs):
        """
        This is a workaround for not being able to share a single websocket across multiple processes.
        At least, not without getting into IPC stuff, which seems like a bad idea.
        Basically, defer connecting the websocket until the first time a call is made to it.
        This _does_ mean that there will be one connection per thread/process using it.
        """
        if not self.is_connected:
            self.ws = self.ws_connect()
            logging.warning(f"OBS command: first connect.")
            self.is_connected = True
        return self.ws.call(*args, **kwargs)

    def disconnect(self):
        logging.info("OBS command: disconnect.")
        self.ws.disconnect()
        self.is_connected = False

    def get_scenes(self):
        logging.info("OBS command: get all scenes.")
        self.scenes = self.ws_call(requests.GetSceneList())

    def go_brb(self):
        logging.info("OBS command: switch to BRB scene.")
        # self.media_source_toggle()
        return self.ws_call(requests.SetCurrentScene(self.brb_scene))

    def go_normal(self):
        logging.info("OBS command: switch to normal scene.")
        self.media_source_toggle()
        return self.ws_call(requests.SetCurrentScene(self.normal_scene))

    def start_stream(self):
        logging.info("OBS command: start stream.")
        return self.ws_call(requests.StartStreaming())

    def stop_stream(self):
        logging.info("OBS command: stop stream.")
        return self.ws_call(requests.StopStreaming())

    def stream_status(self):
        logging.info("OBS command: get stream status.")
        return self.ws_call(requests.GetStreamingStatus())

    def get_current_scene(self):
        logging.info("OBS command: get current scene.")
        return self.current_scene

    @property
    def current_scene(self):
        logging.debug(f"OBS property: current_scene.")
        return self.ws_call(requests.GetCurrentScene()).getName()

    def get_media_sources(self):
        srcs = self.ws_call(requests.GetSourcesList()).getSources()
        media_src_types = ("vlc_source", "ffmpeg_source")
        media_sources = [x for x in srcs if x['typeId'] in media_src_types]
        logging.debug(f"OBS command: get media sources.\n{media_sources}")
        return media_sources

    @property
    def active_media_source(self, live_scene_name="IRL Input"):
        # This assumes that the only visible media source is active.
        logging.debug(f"OBS property: active_media_source.")
        srcs = self.get_media_sources()
        for s in srcs:
            k = s["name"]
            if self.ws_call(requests.GetSceneItemProperties(k, live_scene_name)).getVisible():
                return k

    def stop_media_source(self, source_name):
        logging.debug(f"OBS command: stop media source '{source_name}'.")
        return self.ws_call(requests.StopMedia(source_name))

    def play_media_source(self, source_name):
        logging.debug(f"OBS command: play media source '{source_name}'.")
        return self.ws_call(requests.PlayPauseMedia(source_name, "play"))

    def pause_media_source(self, source_name):
        logging.debug(f"OBS command: pause media source '{source_name}'.")
        return self.ws_call(requests.PlayPauseMedia(source_name, "pause"))

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
        pass
        #active_src = self.active_media_source
        # src_settings = self.ws_call(requests.GetSourceSettings(active_src)).getSourceSettings()
        # if "seekable" not in src_settings:
        #     logging.warning(f"OBS command: toggle failed, {active_src} not a Media Source.")
        # else:
        #     s = src_settings["seekable"]
        #     logging.warning(f"OBS command: toggle {active_src} from {s} to {not s}.")
        #     self.ws_call(requests.SetSourceSettings(active_src, {"seekable": not s}))

    # def __str__(self):
    #     return f"Scenes: {self.scenes}, normal name: {self.normal_scene}, brb name: {self.brb_scene}."


class OBSControl(threading.Thread):
    def __init__(self, srt_thread, websocket, shared_state, config_path="srt_config.toml"):
        super().__init__()
        self.event = threading.Event()
        self.config = get_config(config_path)
        self.srt_cfg = self.config["srt_relay"]
        self.srt_thread = srt_thread
        self.obs_cfg = self.config["obs"]
        self.thresholds = self.config["brb_thresholds"]
        self.brb_scene = self.obs_cfg["brb_scene_name"]
        self.stabilize_dec = self.thresholds["check_interval"]
        self.obs_websoc = websocket
        self.ra_samples = self.thresholds["running_avg"]
        self.bitrate_samples = [None for _ in range(self.ra_samples)]
        self.rtt_samples = [None for _ in range(self.ra_samples)]
        self.connected = False
        #  5 added because it seemed too short otherwise. This seems like a hack...
        self.update_timeout = timedelta(seconds=self.stabilize_dec * self.ra_samples * 5)
        self.cooldown_timeout = timedelta(seconds=self.thresholds["cooldown_time"])
        self.cooldown_timer = datetime.now()
        self.start_time = datetime.now()
        self.name="OBSctrl"
        self.shared_state = shared_state
        # Make sure we're on our live scene.
        self.obs_websoc.go_normal()

    @property
    def scene_locked(self):
        res = self.shared_state.get("scene_lock")
        logging.debug(f"OBSControl: scene_locked() -> {res}")
        return res

    @scene_locked.setter
    def scene_locked(self, v):
        res = bool(v)
        logging.debug(f"OBSControl: scene_locked({res})")
        return self.shared_state.put("scene_lock", res)

    @property
    def bitrate_ra(self):
        res = sum([x for x in self.bitrate_samples if not x in (None, 0)]) / self.ra_samples
        return round(res, 2) 

    @property
    def rtt_ra(self):
        res = sum([x for x in self.rtt_samples if not x in (None, 0)]) / self.ra_samples
        return round(res, 2)

    def run(self):
        logging.info("OBSControl thread started.")

        stabilize_countdown = 0
        idx = 0
        healthy = False
        while not self.event.is_set():
            idx += 1
            current_scene = self.obs_websoc.current_scene
            logging.debug(f"Current scene: {current_scene}, countdown: {round(stabilize_countdown, 2)}.")
            stats = self.srt_thread.last_stats
            stats_time = self.srt_thread.last_update
            timestamp = datetime.now()

            # track connection state
            self.connected = self.srt_thread.connected

            # If the source disconnects due to a drop without explicitly disconnecting, we should go brb.
            # This is explicitly needed because the stats don't update in this case, so the code never sees the bitrate disappear.
            # We should only complain about a failure to update stats when the source is connected. There may be an edge case here.
            last_update_delta = timestamp - stats_time
            stats_fresh = True
            if last_update_delta >= self.update_timeout and self.connected and healthy:
                logging.warning(f"SRT: Stats have not been updated for: {last_update_delta}, which is longer than cutoff: {self.update_timeout}.")
                healthy = False
                # Otherwise the health checks use stale stats, and while this check doesn't need to be before this part, this seems cleaner.
                stats_fresh = False
                stats = {}
                
            if stats != {} and stats_fresh:
                bitrate_healthy = self.check_bitrate_health(idx)
                rtt_healthy = self.check_rtt_health(idx)
                if bitrate_healthy is None:
                    bitrate_healthy = True
                    logging.info(f"SRT: sid: {str(stats['sid'])[-2:]}: Skipping! {stats['send']['mbitRate']}, {stats['recv']['mbitRate']}")
                    stats = {}
                if bitrate_healthy and rtt_healthy:
                    logging.info(f"SRT: Healthy, Bitrate: {self.bitrate_ra}Mb/s, RTT: {self.rtt_ra}ms.")
                    healthy = True
                else:
                    healthy = False
            elif stats == {} and stats_fresh:
                logging.info(f"SRT stats blank.")
            else:
                pass

            if not self.connected:
                healthy = False
            else:
                pass
                # healthy = True

            if stats != {}:
                logging.debug(f"rtt: {self.rtt_ra}, bitrate: {self.bitrate_ra}, healthy: {healthy}, locked: {self.scene_locked}, connected: {self.connected}.")
                logging.debug(f"rtt hist: {self.rtt_samples}, bitrate hist: {self.bitrate_samples}, update delta: {last_update_delta}.")
            else:
                logging.debug(f"No stats. Healthy: {healthy}, locked: {self.scene_locked}, connected: {self.connected}.")
                logging.debug(f"rtt hist: {self.rtt_samples}, bitrate hist: {self.bitrate_samples}, update delta: {last_update_delta}.")

            if not self.scene_locked and not self.connected:
            # if not self.obs_websoc.scene_locked and not self.connected:
                healthy = False

            # If scene has been manually locked, don't switch scenes, even if we otherwise should.
            if self.scene_locked:
                pass
            elif healthy:
                if stabilize_countdown >= 0.0:
                    stabilize_countdown -= self.stabilize_dec
                    logging.info(f"SRT: in stabilization countdown: {round(stabilize_countdown, 2)}s.")
                elif current_scene == self.brb_scene and stabilize_countdown <= 0.0:
                    logging.warning(f"SRT: stabilization countdown finished.")
                    self.obs_websoc.go_normal()
            elif current_scene != self.brb_scene:
                logging.info(f"SRT: cooldown timer: {self.cooldown_timer}")
                if timestamp > self.cooldown_timer:
                    logging.warning(f"SRT: Switching to BRB scene.")
                    self.obs_websoc.go_brb()
                    stabilize_countdown = self.thresholds["stabilize_time"]
                    self.cooldown_timer = datetime.now() + self.cooldown_timeout
                else:
                    logging.info(f"BRB triggered, but on cooldown for {timestamp - self.cooldown_timeout}.")
            else:
                logging.info(f"Current scene: {current_scene}")
                logging.debug(f"SRT: starting stabilization countdown {stabilize_countdown}")
                if stabilize_countdown <= 0:
                    stabilize_countdown = self.thresholds["stabilize_time"]
                else:
                    stabilize_countdown -= self.stabilize_dec

            logging.debug(f"SRT: next update in {self.thresholds['check_interval']}s")
            self.event.wait(self.thresholds["check_interval"])

    def stop(self):
        logging.info(f"Stopping OBS control thread started at {self.start_time}.")
        self.event.set()

    def check_bitrate_health(self, idx):
        """
        Handles the bitrate health checks. If the bitrate threshold is -1, skip checking.
        """
        logging.debug("Health check: Bitrate.")
        if self.thresholds["bitrate"] == -1:
            return True
        stats = self.srt_thread.last_stats
        # When the stats are (0, 0), this could trigger a spurious disconnect.
        # For whatever reason, srt-live-transmit will report a 0 bitrate, even if bits are being sent.
        # So this should be ignored. This may cause an issue with actual 0 birates, but if the bitrate is under any circumstances, then the brb scene should probably be switched to.
        if (stats["send"]["mbitRate"], stats['recv']['mbitRate']) != (0, 0):
            # This is a workaround for not always getting the same stats.
            max_bitrate = max(stats["send"]["mbitRate"], stats['recv']['mbitRate'])
            self.bitrate_samples[idx % self.ra_samples] = max_bitrate

            logging.debug(f"SRT: sid: {str(stats['sid'])[-2:]}: tx: {stats['send']['mbitRate']}, rx: {stats['recv']['mbitRate']}")
            bitrate_healthy = self.bitrate_ra >= self.thresholds["bitrate"]
            if not bitrate_healthy:
                logging.warning(f"SRT: Bitrate failed health check. Bitrate: {self.bitrate_ra}Mb/s.")
                return False
            else:
                return True
        else:
            return None

    def check_rtt_health(self, idx):
        """
        Handles the RTT health checks. If the RTT threshold is -1, skip checking.
        """
        logging.debug("Health check: RTT.")
        if self.thresholds["rtt"] == -1:
            return True
        stats = self.srt_thread.last_stats
        self.rtt_samples[idx % self.ra_samples] = stats["link"]["rtt"]
        logging.debug(f"SRT: sid: {str(stats['sid'])[-2:]}: {stats['link']['rtt']}")
        rtt_healthy = self.rtt_ra <= self.thresholds["rtt"]
        if not rtt_healthy:
            logging.warning(f"SRT: Failed health check. RTT: {self.rtt_ra}ms.")
            return False
        return True

def start_srt(config):
    srt_cfg = config["srt_relay"]
    srt_passphrase = srt_cfg["encryption_passphrase"]
    srt_thread = SRTThread(
        srt_destination=f"srt://:{srt_cfg['output_port']}",
        srt_source=f"srt://localhost:4001",
        passphrase=srt_passphrase,
        srt_live_transmit=srt_cfg['srtla_slt_path'],
        loss_max_ttl=srt_cfg['srt_latency'],
        srt_latency=srt_cfg['loss_max_ttl'],)
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
