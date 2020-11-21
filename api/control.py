import falcon
import json
from os import path, getcwd
import toml
import pprint
import re
import threading

import gstd_streaming as gstds
from pygstc.gstc import *
from collections import namedtuple
from time import sleep
from datetime import datetime
import subprocess

def find_devices():
    """
    Used to determine the device node of the different devices.
    Returns:
        Dictionary, with the being the name of the device, and the value a list of ["/dev/videoX", "usb-id"].
    """
    res = subprocess.run(
        ["v4l2-ctl", "--list-devices"], stdout=subprocess.PIPE, universal_newlines=True
    )
    # output has the form:
    # 'Cam Link 4K (usb-70090000.xusb-1.4):'
    # '   /dev/video0'
    cleaned = [x for x in res.stdout.split("\n") if x != ""]
    devices = {}
    for idx in range(0, len(cleaned), 2):
        dev = cleaned[idx + 1][1:]
        name, usb = cleaned[idx][:-2].split(" (usb-")
        usb = "usb-" + usb
        devices[name] = [dev, usb]
    return devices


def read_config(config_path="config.toml"):
    """
    Open the config file.
    Args:
        config_path (str, optional): Reads the configuration toml file. By default loads "config.toml" from the currenct directory. Defaults to "config.toml".
    Returns:
        dict: Configuration values.
    """
    with open(config_path, 'r') as f:
        config = toml.load(f)
    return config


def parse_url(url):
    """
    Takes a URL of the form srt://srt-ingest:4000 or udp://udp-ingest:4000.
    Args:
        url (str): URL to parse.
    Returns:
        (tuple): (protocol, hostname, port)
    """
    protocol, hostname, port = re.split('://|:', url)
    return protocol.lower(), hostname, int(port)


def create_pipelines(client, config, debug=False):
    """
    Creates the pipelines as specified in the configuration TOML file, details in the readme.
    Conceptually, there are two input pipelines and one output pipeline, that uses gst-interpipe to switch between the two.
        This output includes the encoder.
    Args:
        client (GstdClient): fstd client to use for commands.
        config (dict): Configuration file to use to create the pipelines.
        debug (bool, optional): Print debugging information. Defaults to False.
    Returns:
        tuple(dictionary, dictionary).
            The first dictionary contains the pipelines, and the key is the pipeline name and the value is the pipeline.
            The second contains metadata on the pipelines, currently only which input is active and the bitrate.
    """
    encoder_config = config['encoder']
    input1_config = config['input1']
    input2_config = config['input2']
    output_config = config['output1']

    initial_input = "input1"
    if "default" in input2_config.keys():
        initial_input = "input2"

    devices = find_devices()
    input1_dev = [devices[x] for x in devices.keys() if input1_config['name'] in x][0][0]
    input2_dev = [devices[x] for x in devices.keys() if input2_config['name'] in x][0][0]

    if debug:
        print(f"Connected devices: {devices}")
        print(f"input1 using: {input1_dev}, input2 using: {input2_dev}.")
        print("\nParsed config TOML:")
        pp = pprint.PrettyPrinter(compact=False)
        print("\nEncoder config:")
        pp.pprint(encoder_config)
        print("\nFirst input config:")
        pp.pprint(input1_config)
        print("\nSecond input config:")
        pp.pprint(input2_config)
        print("\nOutput config:")
        pp.pprint(output_config)

    # Common interpipesink options for inputs.
    interpipe_sink_options = (
        "sync=false async=false forward-events=true forward-eos=true"
    )
    input1_gst = f"v4l2src device={input1_dev} ! {input1_config['gst']} ! interpipesink name=input1 {interpipe_sink_options}"
    if debug:
        print("input1 gst:", input1_gst)
    input1_config["full_gst"] = input1_gst
    input1 = gstds.Pipeline(gstdclient=client, name="input1", config=input1_config, debug=debug)
    input2_gst = f"v4l2src device={input2_dev} ! {input2_config['gst']} ! interpipesink name=input2 {interpipe_sink_options}"
    if debug:
        print("input2 gst:", input2_gst)
    input2_config["full_gst"] = input2_gst
    input2 = gstds.Pipeline(gstdclient=client, name="input2", config=input2_config, debug=debug)

    pipelines = {"input1": input1, "input2": input2}

    output1_inter = (
        f"interpipesrc format=time listen-to={initial_input} block=true name=output1"
    )


    # This is messy and should probably be handled elsewhere.
    # But the name of the encoder sometimes changes if gstd isn't restarted between invocations of this program.
    # So we find the current name. The number at the end is what changes.
    protocol, hostname, port = parse_url(output_config['url'])
    output1_sink = f"h265parse ! mpegtsmux ! rndbuffersize max=1316 min=1316 ! udpsink host=localhost port=4200"
    encoder_input = f"nvvidconv !  textoverlay text=bitrate: ! nvvidconv "
    output1_gst = f"{output1_inter} ! {encoder_input} ! {encoder_config['gst']} ! {output1_sink}"
    if debug:
        print("output1 gst:", output1_gst)

    output_config["full_gst"] = output1_gst
    output1 = gstds.Output(gstdclient=client, name="output1", config=output_config, encoder_config=encoder_config, debug=debug)

    pipelines["output1"] = output1

    pipelines_meta = {"active_input": initial_input}
    return pipelines, pipelines_meta


def start_pipelines(pipelines):
    """
    Convenience function to start the pipelines.
    """
    for p in pipelines.values():
        p.play()

def stop_pipelines(pipelines):
    """
    Convenience function to stop the pipelines.
    """
    for p in pipelines.values():
        print(f"[{datetime.now()}] Attempting to cleanup {p.name}.")
        p.cleanup()

def setup(debug):
    """
    Convenience function to set everything up.
    """
    config = read_config()

    client = GstdClient()
    pipelines, pipelines_meta = create_pipelines(client, config, debug=debug)

    start_pipelines(pipelines)
    encoder_name = [x for x in pipelines["output1"].list_elements() if "nvv4l2h265enc" in x["name"]][0]["name"]
    pipelines["output1"].encoder = encoder_name
    pipelines["output1"].set_bitrate()
    return pipelines, pipelines_meta


class BitrateWatcherThread(threading.Thread):
    def __init__(self, output_pipeline, srt_stats, update_interval=0.5, debug=False):
        self.output_config = read_config()["output1"]
        self.output_pipe = output_pipeline
        self.srt = srt_stats
        self.event = threading.Event()
        self.rtt_backoff_threshold = self.output_config["backoff_rtt"]
        self.rtt_normal_threshold = self.output_config["backoff_rtt_normal"]
        self.cooldown_time = self.output_config["backoff_retry_time"]
        self.update_interval=update_interval
        self.backoff = 0
        self.debug = debug
        super().__init__(group=None)

    def run(self):
        bitrate_steps = self.output_pipe.bitrate_steps
        while not self.event.is_set():
            cooldown = 0
            stats = self.srt.last_stats
            if stats == {}:
                continue
            rtt = stats["link"]["rtt"]
            if self.debug:
                print("bw:", bitrate_steps, self.output_pipe.current_bitrate, "rtt:", rtt, "backoff:", self.backoff, "locked:", self.output_pipe.bitrate_locked)
            # To override the backoff behaviour.
            if self.output_pipe.bitrate_locked:
                # If the bitrate is manually locked, don't switch, even if we otherwise would be.
                pass
            elif self.backoff >= 0 and rtt >= self.rtt_backoff_threshold:
                self.backoff = max(0, min(self.backoff + 1, len(bitrate_steps)))
                self.output_pipe.current_bitrate = bitrate_steps[self.backoff]
                if debug:
                    print(f"BitrateWatcher: Drop bitrate to {bitrate_steps[self.backoff]}. RTT: {rtt}, backoff: {self.backoff}")
                cooldown = self.cooldown_time
            elif self.backoff > 0 and rtt < self.rtt_normal_threshold:
                self.backoff = max(0, min(self.backoff - 1, len(bitrate_steps)))
                self.output_pipe.current_bitrate = bitrate_steps[self.backoff]
                if self.debug:
                    print(f"BitrateWatcher: Increase bitrate to {bitrate_steps[self.backoff]}. RTT: {rtt}, backoff: {self.backoff}")
                cooldown = self.cooldown_time
            self.event.wait(self.update_interval + cooldown)

    def stop(self):
        """
        Stops the srt-live-transmit process and the stats-gathering loop.
        """
        self.event.set()

if __name__ == "__main__":
    # This is a test to swap between inputs and change the bitrate to ensure everything is working correctly.
    debug = True

    pipelines, pipelines_meta = setup(debug)
    test_bitrates = pipelines["output1"].fallback_bitrates
    idx = 0
    sleep_time = 5
    text = [x["name"] for x in pipelines["output1"].list_elements() if "textoverlay" in x["name"]][0]
    if debug:
        print(f"text name: {text}")

    try:
        while True:
            print(f"idx: {idx}")
            idx += 1
            for bitrate in test_bitrates:
                pipelines["output1"].set_bitrate(bitrate)
                # pipelines["output1"].set_property(text, "text", f"bitrate: {bitrate / 1000}kb/s")
                pipelines_meta["bitrate"] = bitrate
                sleep(sleep_time)
            # This switching logic only swaps between two inputs.
            sleep(sleep_time * 2)
            next_input = [x for x in pipelines.keys() if "input" in x and x != pipelines_meta["active_input"]][0]
            pipelines["output1"].switch_src(next_input)
            pipelines_meta["active_input"] = next_input
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(e)
    stop_pipelines(pipelines)