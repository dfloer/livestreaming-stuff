import json
import subprocess
from dataclasses import dataclass


@dataclass(init=False)
class SRTProcess:
    """
    Wrapper class to manage the subprocess driven srt-live-transmit instance.
    """

    stats_interval: int
    src_conn: str
    dst_conn: str

    def __init__(self, stats_interval, src_conn, dst_conn):
        self.stats_interval = stats_interval
        self.src_conn = src_conn
        self.dst_conn = dst_conn

        self.srt_process = self.start_process()

    def start_process(self):
        srt_cmd = f"srt-live-transmit -buffering 1 -s {self.stats_interval} -pf json {self.src_conn} {self.dst_conn}"
        return subprocess.Popen(
            f"{srt_cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

    def kill_process(self):
        self.srt_process.kill()

    def stats_parse(self, raw_stats):
        """
        Parses a raw message from srt-live-transmit, into either a dict or a message.
        Args:
            raw_stats (str): raw output form srt-live-transmit application.
        Returns:
            tuple: message (empty if there isn't one, making this json only), dictionary (empty, otherwise decoded json).
        """
        message = ""
        stats = {}
        try:
            stats = json.loads(raw_stats)
        except json.decoder.JSONDecodeError:
            message = raw_stats
        return stats, message

    # def get_stats(self):

    #     stats, message = self.stats_parse()
    #     return stats, message



if __name__ == "__main__":
    try:
        srt = SRTProcess(100, "udp://:4200", "srt://192.168.0.200:4000")

        ticks = 0
        while True:
            ticks += 1
            rc = srt.srt_process.poll()
            if rc != None:
                print(f"Return code: {rc}")
                break
            output = srt.srt_process.stdout.readline()
            if output == "" and srt.srt_process.poll() is not None:
                break
            if output:
                stats, message = srt.stats_parse(output)
                if stats:
                    guessed_bandwidth = stats["link"]["bandwidth"]
                    if stats["recv"]["mbitRate"] != 0:
                        bitrate = stats["recv"]["mbitRate"]
                    else:
                        bitrate = stats["send"]["mbitRate"]
                    snd_loss = stats["send"]["packetsLost"]
                    rcv_loss = stats["recv"]["packetsLost"]
                    curr_flight = stats["window"]["flight"]
                    curr_flow = stats["window"]["flow"]
                    print(
                        f"Window/Flight: {curr_flight}, Window/Flow: {curr_flow} @ {bitrate} Mb/s."
                    )
                if stats and snd_loss != rcv_loss != 0:
                    print(f"Send loss: {snd_loss}, receive loss: {rcv_loss}.")
    except KeyboardInterrupt:
        srt.kill_process()
        print(f"Keyboard interrupt receiver, killing srt-live-transmit.")
