import threading
import subprocess
import json
from os import set_blocking, getpgid
from datetime import datetime, timedelta
from loguru import logger as logging
from utils import ThreadManager, get_passphrase

class SRTThread(ThreadManager):
    def __init__(self, srt_destination, srt_source, stats_interval=100, update_interval=0.1, passphrase='', srt_live_transmit="srt-live-transmit", loss_max_ttl=50, srt_latency=2000):
        """
        Wrapper thread to start/stop srt-live-transmit and get stats out of it.
        Source and destination as per documentation at: https://github.com/Haivision/srt/blob/master/docs/srt-live-transmit.md
        Args:
            srt_destination (str): Destination srt server to send to.
            srt_source (str): Port and protocol that srt-live-transmit listens on.
            stats_interval (int, optional): How often to update the SRT stats, in _packets_, not time. Defaults to 100.
            update_interval (float, optional): How often to should read stats from the process, too often and it blocks the web thread, not often enough and output from the process gets blocked.. Defaults to 0.1.
            passphrase (str, optional): Passphrase to use for encryption. If this is blank, one will be generated and printed on the console.
            srt_live_transmit (Path, optional): Path to the srt-live-transmit binary. If none specified, will use whatever one is in your path. Defaults to "srt-live-transmit".
            loss_max_ttl (int, optional): Tolerance to packet re-ordering. Defaults to 50.
            srt_latency (int, optional): Maximum acceptable transmission latency. If we go past this, drop the packets. Defaults to 200.
        """
        super().__init__()
        self.stats_interval = stats_interval
        self.update_interval = update_interval
        self.passphrase = get_passphrase(passphrase)
        self.last_message = ''
        self.last_stats = {}
        self._name = "SLT"
        self.last_update = datetime.now()
        self.connected = False
        # srt-live-transmit command variables
        self.srt_exec = srt_live_transmit
        self.loss_max_ttl = loss_max_ttl
        self.srt_latency = srt_latency
        self.src_conn = f"{srt_source}?passphrase={self.passphrase}&enforcedencryption=true&mode=listener&lossmaxttl={self.loss_max_ttl}&latency={self.srt_latency}"
        self.dst_conn = srt_destination
        # Generate the actual command
        self.cmd = f"{self.srt_exec} -srctime -buffering 1 -s {self.stats_interval} -pf json \"{self.src_conn}\" {self.dst_conn}"
        self.start_process()

    def run_inner(self):
        """
        Get the stats and save the last one to this object.
        """
        stats, msg = self.stats_parse()
        if stats:
            self.last_stats = stats[-1]
            self.last_update = datetime.now()
            logging.debug(f"SRT raw stats: {stats}")
            # If the stats have updated, assume that SRT is connected.
            self.connected = True
        if msg:
            self.last_message = msg[-1]
            logging.info(f"SRT Message: {msg}")

        # SRT connection and process health checks.
        self.check_is_connected()
        self.check_time_workaround()

    def run(self):
        self.wait_interval = self.update_interval
        super().run()

    def check_is_connected(self):
        """
        Track connection state, because the switcher uses it to determine health.
        This is only for the incoming connection, not the target connection.
        If that were to break, well, OBS is broken and there isn't much to do...
        """
        if "SRT source disconnected" in self.last_message and self.connected:
            self.connected = False
            logging.warning(f"SRT: Source Disconnected.")
        elif "Accepted SRT source connection" in self.last_message and not self.connected:
            self.connected = True
            logging.warning(f"SRT: Source Connected.")

    def check_time_workaround(self):
        """
        This is a workaround for a clock drift (or something) but in srt-live-transmit.
        It usually takes several (8+) hours to show up in testing.
        Restarting the srt-live-transmit process should fix this.
        """
        if "Wrong source time was provided" in self.last_message:
            logging.error(f"SRT Live Transmit source time error. Process started: {self.start_time}.")
            self.restart_process()
            logging.warning("SRT Live Transmit recovered from source time error.")

    def get_raw_stats(self):
        """
        Get the raw stats from the SRT process.
        Returns:
            bytestring: Raw output strings from srt-live-transmit's stderr and stdout.
        """
        res = []
        idx = 0
        while True:
            idx += 1
            l = self.readline()
            if l == b'':
                break
            res += [l]
        return res

    def stats_parse(self):
        """
        Parses a raw message from srt-live-transmit, into either a dict or a message.
        Returns:
            tuple: message (empty if there isn't one, making this json only), dictionary (empty, otherwise decoded json).
        """
        raw_stats = self.get_raw_stats()
        messages = []
        stats = []
        for line in raw_stats:
            try:
                stats += [json.loads(line)]
            except json.decoder.JSONDecodeError:
                messages += [line.decode('ASCII')]
        return stats, messages

class SRTLAThread(threading.Thread):
    def __init__(self, srtla_rec="srtla_rec", source_port=4000, destination_host="localhost", destination_port=4001):
        self.event = threading.Event()
        self.src_port = source_port
        self.dst_port = destination_port
        self.srtla_exec = srtla_rec
        self.host = destination_host
        self.event = threading.Event()
        self.srtla_process = self.start_process()
        set_blocking(self.srtla_process.stdout.fileno(), False)
        self.start_time = None
        super().__init__(group=None)
        # print("srtla:", self.srtla_process.stdout.read())

    def start_process(self):
        """
        Start the SRTLA process.
        """
        srtla_cmd = f"{self.srtla_exec} {self.src_port} {self.host} {self.dst_port}"
        logging.info(f"Starting SRTLA: {srtla_cmd}")
        self.start_time = datetime.now()
        return subprocess.Popen(
            f"{srtla_cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

    def kill_process(self):
        """
        Start the SRTLA process.
        """
        logging.warning(f"Killing SRTLA process running since: {self.start_time}")
        self.srtla_process.kill()

    def stop(self):
        """
        Stops the srt-live-transmit process and the stats-gathering loop.
        """
        self.kill_process()
        self.event.set()
        logging.info("Stopping SRTLA process")

    def run(self):
        """
        Get the stats and save the last one to this object.
        """
        logging.info("SRTLA thread started.")
        while not self.event.is_set():
            msg = self.srtla_process.stdout.read()
            if msg:
                logging.info(f"SRTLA Message: {msg.decode('ASCII')}")
            self.event.wait(0.1)