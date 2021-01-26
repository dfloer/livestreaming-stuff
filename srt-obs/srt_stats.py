import threading
import subprocess
import select
import json
from os import set_blocking
import secrets


class SRTThread(threading.Thread):
    def __init__(self, srt_destination, srt_source="udp://:4200", stats_interval=100, update_interval=0.1, passphrase=''):
        """
        Wrapper thread to start/stop srt-live-transmit and get stats out of it.
        Source and destination as per documentation at: https://github.com/Haivision/srt/blob/master/docs/srt-live-transmit.md
        Args:
            srt_destination (str): Destination srt server to send to.
            srt_source (str, optional): Port and protocol that srt-live-transmit listens on. Defaults to "udp://:4200"
                Ideally this would be using SRT, but the build of gstreamer that comes with the Jetson doesn't support it.
            stats_interval (int, optional): How often to update the SRT stats, in _packets_, not time. Defaults to 100.
            update_interval (float, optional): How often to should read stats from the process, too often and it blocks the web thread, not often enough and output from the process gets blocked.. Defaults to 0.1.
            passphrase (str, optional): Passphrase to use for encryption. If this is blank, one will be generated and printed on the console.
        """
        self.event = threading.Event()
        self.stats_interval = stats_interval
        self.update_interval = update_interval

        self.passphrase = passphrase
        print("passphrase:", self.passphrase)
        if not self.passphrase:
            self.generate_passphrase()
        div = "----------------------------------------------------------------"
        print(f"\nSRT Passphrase:")
        print(div)
        print(f"{self.passphrase}")
        print(div)

        self.src_conn = f"{srt_source}?passphrase={self.passphrase}&enforcedencryption=true"
        self.dst_conn = srt_destination
        self.srt_process = self.start_process()
        set_blocking(self.srt_process.stdout.fileno(), False)
        self.last_message = ''
        self.last_stats = {}
        super().__init__(group=None)

    def generate_passphrase(self, length=32):
        """
        Generates a passphrase for use with SRT.
        Args:
            length (int, optional): Length of the passphrase to generate. Default 32.
        Returns:
            (str) the passphrase.
        """
        self.passphrase = secrets.token_hex(length)

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
        srt_cmd = f"srt-live-transmit -srctime -buffering 1 -s {self.stats_interval} -pf json \"{self.src_conn}\" {self.dst_conn}"
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