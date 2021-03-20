import threading
import subprocess
import select
import json
from os import set_blocking


class SRTThread(threading.Thread):
    def __init__(self, passphrase, srt_destination, srt_source="udp://:4200", stats_interval=100, update_interval=0.1):
        """
        Wrapper thread to start/stop srt-live-transmit and get stats out of it.
        Source and destination as per documentation at: https://github.com/Haivision/srt/blob/master/docs/srt-live-transmit.md
        Args:
            srt_destination (str): Destination srt server to send to.
            srt_source (str, optional): Port and protocol that srt-live-transmit listens on. Defaults to "udp://:4200"
                Ideally this would be using SRT, but the build of gstreamer that comes with the Jetson doesn't support it.
            stats_interval (int, optional): How often to update the SRT stats, in _packets_, not time. Defaults to 100.
            update_interval (float, optional): How often to should read stats from the process, too often and it blocks the web thread, not often enough and output from the process gets blocked.. Defaults to 0.1.
        """
        self.event = threading.Event()
        self.stats_interval = stats_interval
        self.update_interval = update_interval
        self.passphrase = passphrase
        self.src_conn = srt_source
        # Handle extra args in the config. This should probably be cleaned up at some point.
        d = '?'
        if '?' in srt_destination:
            d = '&'
        self.dst_conn = f"{srt_destination}{d}passphrase={self.passphrase}&enforcedencryption=true"
        self.srt_process = self.start_process()
        set_blocking(self.srt_process.stdout.fileno(), False)
        self.last_message = ''
        self.last_stats = {}
        super().__init__(group=None)

    def run(self):
        """
        Get the stats and save the last one to this object.
        """
        while not self.event.is_set():
            stats, msg = self.stats_parse()
            if stats:
                self.last_stats = stats[-1]
            if msg:
                self.last_message = msg[-1]
                print(f"Message: {msg}")
            self.event.wait(self.update_interval)

    def start_process(self):
        """
        Start the SRT process.
        """
        srt_cmd = f"srt-live-transmit -srctime -buffering 1 -s {self.stats_interval} -pf json {self.src_conn} \"{self.dst_conn}\""
        return subprocess.Popen(
            f"{srt_cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

    def kill_process(self):
        """
        Start the SRT process.
        """
        self.srt_process.kill()

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
            l = self.srt_process.stdout.readline()
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

    def stop(self):
        """
        Stops the srt-live-transmit process and the stats-gathering loop.
        """
        self.kill_process()
        self.event.set()

class SRTLAThread(threading.Thread):
    def __init__(self, srtla_send="srtla_send", source_port=6000, destination_host="localhost", destination_port=4000, ip_file="srtla_ips.txt"):
        self.event = threading.Event()
        self.src_port = source_port
        self.dst_port = destination_port
        self.srtla_exec = srtla_send
        self.host = destination_host
        self.ip_file = ip_file

        self.event = threading.Event()
        self.srtla_process = self.start_process()
        set_blocking(self.srtla_process.stdout.fileno(), False)
        super().__init__(group=None)
        # print("srtla:", self.srtla_process.stdout.read())

    def start_process(self):
        """
        Start the SRTla process.
        """
        srtla_cmd = f"{self.srtla_exec} {self.src_port} {self.host} {self.dst_port} {self.ip_file}"
        print(f"starting srtla: {srtla_cmd}")
        return subprocess.Popen(
            f"{srtla_cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

    def kill_process(self):
        """
        Start the SRT process.
        """
        self.srtla_process.kill()

    def stop(self):
        """
        Stops the srt-live-transmit process and the stats-gathering loop.
        """
        self.kill_process()
        self.event.set()

    def run(self):
        """
        Get the stats and save the last one to this object.
        """
        print("SRTLA thread running.")
        while not self.event.is_set():
            msg = self.srtla_process.stdout.read()
            if msg:
                print(f"SRTLA Message: {msg.decode('ASCII')}")
            self.event.wait(0.1)