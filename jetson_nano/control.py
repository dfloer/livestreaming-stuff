import srt_wrapper
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


def create_pipelines(client):
    """
    Creates the pipelines configured.
    For now this is hardcoded, but this should read a config file at some point.
    Args:
        client (GstdClient): fstd client to use for commands.
    Returns:
        tuple(dictionary, dictionary).
            The first dictionary contains the pipelines, and the key is the pipeline name and the value is the pipeline.
            The second contains metadata on the pipelines, currently only which input is active and the bitrate.
    """
    debug = True
    pipelines = {}

    # common input options for gst-interpipe.
    interpipe_sink_options = (
        "sync=false async=false forward-events=true forward-eos=true"
    )
    initial_input = "input1"
    bitrate = 6000000

    devices = find_devices()
    camlink = [devices[x] for x in devices.keys() if "Cam Link" in x][0][0]
    gc311 = [devices[x] for x in devices.keys() if "Live Gamer" in x][0][0]
    if debug:
        print(f"Connected devices: {devices}")

    # hardcoded (for now) inputs.
    input2_gst = f"v4l2src device={gc311} ! video/x-h264 ! nvv4l2decoder ! nvvidconv ! video/x-raw,format=YUY2 ! timeoverlay text=GC311: ! interpipesink name=input1 {interpipe_sink_options}"
    input1_gst = f"v4l2src device={camlink} ! timeoverlay text=Camlink4k: ! queue ! interpipesink name=input2 {interpipe_sink_options}"
    input1 = gstds.Pipeline(client, "input1", input1_gst, debug)
    pipelines["input1"] = input1
    input2 = gstds.Pipeline(client, "input2", input2_gst, debug)
    pipelines["input2"] = input2

    # Again hardcoded inputs.
    output1_inter = (
        f"interpipesrc format=time listen-to={initial_input} block=true name=output1"
    )
    encoder_input = f"nvvidconv ! timeoverlay halignment=right text=encoder: ! textoverlay text='bitrate: {bitrate / 1000}kb/s' ! nvvidconv "
    output1_encoder = f"nvv4l2h265enc bitrate={bitrate} peak-bitrate={bitrate} iframeinterval=120 insert-vui=1 insert-aud=1 insert-sps-pps=1 control-rate=1 preset-level=4 maxperf-enable=true EnableTwopassCBR=true"
    output1_sink = "h265parse ! mpegtsmux ! rndbuffersize max=1316 min=1316 ! udpsink host=192.168.0.200 port=4000"
    output1_gst = (
        f"{output1_inter} ! {encoder_input} ! {output1_encoder} ! {output1_sink}"
    )
    output1 = gstds.Pipeline(client, "output1", output1_gst, debug)
    pipelines["output1"] = output1

    pipelines_meta = {"bitrate": bitrate, "active_input": initial_input}
    return pipelines, pipelines_meta


if __name__ == "__main__":
    # check if running/start gstd. Maybe run this in subprocess.
    debug = True
    target_bitrate = 4500000  # target bitrate, in bits/second.
    fallback_bitrates = (
        3000000,
        1500000,
    )  # If the WAN link(s) aren't able to keep up, fallback to trying these.

    test_bitrates = tuple([target_bitrate]) + fallback_bitrates + tuple([fallback_bitrates[0]]) + tuple([target_bitrate])
    client = GstdClient()

    pipelines, pipelines_meta = create_pipelines(client)

    for p in pipelines.values():
        p.play()

    # For some reason the name of the encoder changes between runs while gstd is still running.
    encoder = [
        x["name"]
        for x in pipelines["output1"].list_elements()
        if "nvv4l2h265enc" in x["name"]
    ][0]
    text = [
        x["name"]
        for x in pipelines["output1"].list_elements()
        if "textoverlay" in x["name"]
    ][0]
    if debug:
        print(f"Encoder name: {encoder}")
        print(f"text name: {text}")

    idx = 0
    sleep_time = 5
    try:

        while True:
            print(f"idx: {idx}")
            idx += 1
            for bitrate in test_bitrates:
                pipelines["output1"].set_bitrate(encoder, bitrate)
                pipelines["output1"].set_property(text, "text", f"bitrate: {bitrate / 1000}kb/s")
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

    for p in pipelines.values():
        print(f"[{datetime.now()}] Attempting to cleanup {p.name}.")
        p.cleanup()
