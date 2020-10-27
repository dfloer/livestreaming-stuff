from time import sleep
from pygstc.gstc import *
import gstd_streaming as gstds
from datetime import datetime


if __name__ == "__main__":
    pipelines_input = []
    pipelines_enc = []
    client = GstdClient()
    debug = True

    interpipe_sink_options = "sync=false async=false forward-events=true forward-eos=true"

    input2_gst = f"v4l2src device=/dev/video1 ! video/x-h264 ! nvv4l2decoder ! nvvidconv ! video/x-raw,format=YUY2 ! timeoverlay text=GC311: ! queue ! interpipesink name=input1 {interpipe_sink_options}"
    input1_gst = f"v4l2src device=/dev/video0 ! timeoverlay text=Camlink4k: ! queue ! interpipesink name=input2 {interpipe_sink_options}"
    # input1_gst = "videotestsrc pattern=smpte is-live=true ! video/x-raw,width=1920,height=1080,framerate=30/1 ! timeoverlay text=input1: ! queue ! interpipesink name=input1 sync=false async=false forward-events=true forward-eos=true"
    # input2_gst = "videotestsrc pattern=smpte is-live=true ! video/x-raw,width=1920,height=1080,framerate=30/1 ! videoflip method=horizontal-flip ! timeoverlay text=input2: ! queue ! interpipesink name=input2 sync=false async=false forward-events=true forward-eos=true"

    input1 = gstds.Pipeline(client, "input1", input1_gst, debug)
    pipelines_input.append(input1)

    input2 = gstds.Pipeline(client, "input2", input2_gst, debug)
    pipelines_input.append(input2)

    output1_inter = "interpipesrc format=time listen-to=input1 block=true name=output1"
    encoder_input = "nvvidconv ! timeoverlay halignment=right text=encoder: ! textoverlay text=test ! nvvidconv"
    output1_encoder = "nvv4l2h265enc bitrate=3500000 peak-bitrate=3500000 iframeinterval=60 insert-vui=1 insert-aud=1 insert-sps-pps=1 control-rate=1 preset-level=4 maxperf-enable=true EnableTwopassCBR=true"
    output1_sink = "h265parse ! mpegtsmux ! rndbuffersize max=1316 min=1316 ! udpsink host=192.168.0.200 port=4000"
    output1_gst = f"{output1_inter} ! {encoder_input} ! {output1_encoder} ! {output1_sink}"
    output1 = gstds.Pipeline(client, "output1", output1_gst, debug)
    pipelines_enc.append(output1)

    for p in pipelines_input + pipelines_enc:
        # print(p)
        p.play()

    # For some reason the name of the encoder changes between runs while gstd is still running.
    encoder = [x["name"] for x in pipelines_enc[0].list_elements() if "nvv4l2h265enc" in x["name"]][0]
    text = [x["name"] for x in pipelines_enc[0].list_elements() if "textoverlay" in x["name"]][0]
    if debug:
        print(f"Encoder name: {encoder}")
        print(f"text name: {text}")

    test_bitrates = (1500000, 3000000, 4500000, 6000000)
    idx = 0
    sleep_time = 10
    try:
        while True:
            print(f"idx: {idx}")
            idx += 1
            for bitrate in test_bitrates:
                output1.set_bitrate(encoder, bitrate)
                output1.set_property(text, "text", f"bitrate: {bitrate / 1000}kb/s")
                sleep(sleep_time)
            # sleep(sleep_time * 2)

            output1.switch_src(input2.name)
            # sleep(0.1)

            for bitrate in test_bitrates:
                output1.set_bitrate(encoder, bitrate)
                output1.set_property(text, "text", f"bitrate: {bitrate / 1000}kb/s")
                sleep(sleep_time)
            # sleep(sleep_time * 2)
            output1.switch_src(input1.name)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(e)

    for p in pipelines_input + pipelines_enc:
        print(f"[{datetime.now()}] Attempting to cleanup {p.name}.")
        p.cleanup()
