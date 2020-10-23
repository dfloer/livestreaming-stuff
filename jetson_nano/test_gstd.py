import time
from pygstc.gstc import *
import gstd_streaming as gstds


if __name__ == "__main__":
    pipelines_input = []
    pipelines_enc = []
    client = GstdClient()
    debug = True

    input1_gst = "videotestsrc pattern=smpte is-live=true ! video/x-raw,width=1920,height=1080,framerate=30/1 ! timeoverlay text='input1:' ! queue ! interpipesink name=input1 sync=false async=false forward-events=true forward-eos=true"
    input1 = gstds.Pipeline(client, "input1", input1_gst, debug)
    pipelines_input.append(input1)

    input2_gst = "videotestsrc pattern=ball is-live=true ! video/x-raw,width=1920,height=1080,framerate=30/1 ! timeoverlay text='input2:' ! queue ! interpipesink name=input2 sync=false async=false forward-events=true forward-eos=true"
    input2 = gstds.Pipeline(client, "input2", input2_gst, debug)
    pipelines_input.append(input2)

    output1_gst = "interpipesrc format=time listen-to=input1 block=true name=output1 ! nvvidconv ! nvv4l2h265enc bitrate=3500000 peak-bitrate=3500000 iframeinterval=60 ! h265parse ! mpegtsmux ! filesink location=/tmp/test.video"
    output1 = gstds.Pipeline(client, "output1", output1_gst, debug)
    pipelines_enc.append(output1)

    for p in pipelines_input + pipelines_enc:
        print(p)
        print(p.list_elements())
        p.play()

    output1.set_bitrate("nvv4l2h265enc0", 1500000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 3000000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 4500000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 6000000)
    time.sleep(10)

    output1.switch_src(input2.name)

    output1.set_bitrate("nvv4l2h265enc0", 1500000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 3000000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 4500000)
    time.sleep(10)
    output1.set_bitrate("nvv4l2h265enc0", 6000000)
    time.sleep(10)

    for p in pipelines_input + pipelines_enc:
        print(f"Attempting to cleanup {p.name}.")
        p.cleanup()
