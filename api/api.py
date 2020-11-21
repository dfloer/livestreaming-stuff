import json
import falcon
import control
import requests

class Inputs(object):
    def __init__(self, input1, input2, output_pipeline):
        self.input1_pipeline = input1
        self.input2_pipeline = input2
        self.output_pipeline = output_pipeline
        self.active_input = self.output_pipeline.get_property(self.output_pipeline.name, 'listen-to')

    def as_json(self):
        which = self.active_input
        nice_name = self.input1_pipeline.nice_name if which == self.input1_pipeline.name else self.input2_pipeline.nice_name
        j = {"active_input": which, "nice_name": nice_name}
        return json.dumps(j, ensure_ascii=False)

    def swap_inputs(self):
        if self.active_input == self.input1_pipeline.name:
            swap_to = "input2"
        else:
            swap_to = "input1"
        self.active_input = swap_to
        self.output_pipeline.switch_src(swap_to)
        print("inputs swapped")

    def activate_input(self, inp):
        self.active_input = inp
        self.output_pipeline.switch_src(inp)
        print(f"Input activated: {inp}")

    def on_get(self, req, res, input_name=''):
        res.body = self.as_json()
        res.status = falcon.HTTP_200

    def on_post(self, req, res, input_name=''):
        err = False
        if input_name == "swap":
            self.swap_inputs()
        elif input_name == "input1":
            self.activate_input(input_name)
        elif input_name == "input2":
            self.activate_input(input_name)
        elif input_name == '':
            pass
        else:
            err = True

        res.body = self.as_json()
        if not err:
            res.status = falcon.HTTP_200
        else:
            res.status = falcon.HTTP_404

class Outputs(object):
    def __init__(self, output_pipeline):
        self.output_pipeline = output_pipeline
        self.bitrate_steps = self.output_pipeline.fallback_bitrates
        self.target_bitrate = self.output_pipeline.bitrate
        self.current_bitrate = self.target_bitrate
        self.bitrate_locked = False

    def as_json(self):
        j = {
            "current_bitrate": self.current_bitrate,
            "bitrate_steps": self.bitrate_steps,
        }
        return json.dumps(j, ensure_ascii=False)

    def on_get(self, req, res):
        res.body = self.as_json()
        res.status = falcon.HTTP_200

    def on_post(self, req, res, bitrate=None):
        """
        Bitrate could be a numeric value, but "reset", "inc" and "dec" are also supported.
        """
        post_contents = req.bounded_stream.read()

        bitrate_idx = self.bitrate_steps.index(self.current_bitrate)
        if bitrate == "reset":
            self.current_bitrate = self.target_bitrate
            self.bitrate_locked = False
        elif bitrate == "dec":
            new_idx = max(0, min(bitrate_idx + 1, len(self.bitrate_steps)))
            self.current_bitrate = self.bitrate_steps[new_idx]
            self.bitrate_locked = True
        elif bitrate == "inc":
            new_idx = max(0, min(bitrate_idx - 1, len(self.bitrate_steps)))
            self.current_bitrate = self.bitrate_steps[new_idx]
            self.bitrate_locked = True
        else:
            # This might get overwritten by the below.
            res.body = json.dumps({"error": "invalid bitrate"}, ensure_ascii=False)
            res.status = falcon.HTTP_400
        try:
            bitrate = int(json.loads(post_contents)["current_bitrate"])
            if bitrate in self.bitrate_steps:
                self.current_bitrate = bitrate
                res.status = falcon.HTTP_200
                res.body = self.as_json()
            else:
                res.status = falcon.HTTP_400
                res.body = json.dumps({"error": "bitrate not in bitrate_steps"}, ensure_ascii=False)
        except Exception:
            res.body = json.dumps({"error": "invalid bitrate"}, ensure_ascii=False)
            res.status = falcon.HTTP_400
        self.output_pipeline.set_bitrate(self.current_bitrate)

class SRT(object):
    def __init__(self, srt):
        self.srt_output = srt
        self.stats = {"flow": 0, "flight": 0, "rtt": 0, "send_dropped": 0, "bitrate": 0.0}
        self.srt_message = ''

    def on_get(self, req, res):
        srt_stats = self.srt_output.last_stats
        self.srt_message = self.srt_output.last_message
        try:
            self.stats["flow"] = srt_stats["window"]["flow"]
            self.stats["flight"] = srt_stats["window"]["flight"]
            self.stats["rtt"] = srt_stats["link"]["rtt"]
            if srt_stats["send"]["packetsDropped"] != 0:
                self.stats["send_dropped"] = srt_stats["send"]["packetsDropped"]
            if srt_stats["send"]["mbitRate"] != 0:
                self.stats["bitrate"] = srt_stats["send"]["mbitRate"]
        except Exception:
            # Sometimes the stats are blank, so we'll just send the 0'd json.
            pass
        doc = {
            "stats": self.stats,
            "output": self.srt_output.dst_conn,
            "message": str(self.srt_message)
        }

        res.body = json.dumps(doc, ensure_ascii=False)
        res.status = falcon.HTTP_200


class Stream(object):
    def __init__(self, output=''):
        self.output_string = "srt://srt-ingest:4000"


class StreamControls(object):
    def __init__(self, stream_remote):
        self.stream_remote = stream_remote

    def on_post(self, req, res):
        # post_contents = req.bounded_stream.read()
        if 'start' in req.url:
            # self.pipelines, _ = control.setup(True)
            self.stream_remote.start_stream()
            msg = "Stream started."
        elif 'stop' in req.url:
            # control.stop_pipelines(self.pipelines)
            self.stream_remote.stop_stream()
            msg = "Stream stopped."
        elif 'brb' in req.url:
            self.stream_remote.brb_stream()
            msg = "Stream BRBed."
        elif "back" in req.url:
            self.stream_remote.back_stream()
            msg = "Stream backed."

        res.body = json.dumps({"message": msg}, ensure_ascii=False)
        res.status = falcon.HTTP_200

    def on_get(self, req, res):
        status = self.stream_remote.get_status()
        print(status)
        res.body = json.dumps(status, ensure_ascii=False)
        res.status = falcon.HTTP_200