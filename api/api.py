import json
import falcon
import control
import requests
import urllib
from loguru import logger as logging

class Inputs(object):
    def __init__(self, input1, input2, output_pipeline):
        self.input1_pipeline = input1
        self.input2_pipeline = input2
        self.output_pipeline = output_pipeline
        self.active_input = self.output_pipeline.get_property(self.output_pipeline.name, 'listen-to')

    def as_json(self):
        which = self.active_input
        nice_name = self.input1_pipeline.nice_name if which == self.input1_pipeline.name else self.input2_pipeline.nice_name
        j = {"active_input": which, "nice_name": nice_name, "total_inputs": 2}
        logging.debug(f"Inputs: json: {j}")
        return json.dumps(j, ensure_ascii=False)

    def swap_inputs(self):
        if self.active_input == self.input1_pipeline.name:
            swap_to = "input2"
        else:
            swap_to = "input1"
        self.active_input = swap_to
        self.output_pipeline.switch_src(swap_to)
        logging.info("Inputs: inputs swapped")

    def activate_input(self, inp):
        self.active_input = inp
        self.output_pipeline.switch_src(inp)
        logging.info(f"Inputs: activated: {inp}")

    def on_get(self, req, res, input_name=''):
        res.text = self.as_json()
        res.status = falcon.HTTP_200
        logging.debug(f"Inputs: on_get() called.")

    def on_post(self, req, res, input_name=''):
        err = False
        logging.debug(f"Inputs: on_post() called with: {input_name}.")
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

        res.text = self.as_json()
        if not err:
            res.status = falcon.HTTP_200
            logging.debug(f"Inputs: on_post() success.")
        else:
            res.status = falcon.HTTP_404
            logging.warning(f"Inputs: on_post() failed.")

class Outputs(object):
    def __init__(self, output_pipeline):
        self.output_pipeline = output_pipeline
        self.bitrate_steps = self.output_pipeline.fallback_bitrates
        self.target_bitrate = self.output_pipeline.bitrate
        self.current_bitrate = self.target_bitrate
        self.bitrate_locked = False

    @property
    def state(self):
        return self.output_pipeline.state

    def as_json(self):
        j = {
            "current_bitrate": self.current_bitrate,
            "bitrate_steps": self.bitrate_steps,
            "state": self.state,
        }
        logging.debug(f"Outputs: json: {j}")
        return json.dumps(j, ensure_ascii=False)

    def on_get(self, req, res):
        res.text = self.as_json()
        res.status = falcon.HTTP_200

    def on_post(self, req, res, bitrate=None):
        """
        Bitrate could be a numeric value, but "reset", "inc" and "dec" are also supported.
        """
        post_contents = req.bounded_stream.read()

        bitrate_idx = self.bitrate_steps.index(self.current_bitrate)
        logging.debug(f"Outputs: bitrate stats: mode: {bitrate} current: {self.current_bitrate}, target: {self.target_bitrate}, idx: {bitrate_idx}, locked: {self.bitrate_locked}")
        if bitrate == "reset":
            self.current_bitrate = self.target_bitrate
            self.bitrate_locked = False
            logging.debug(f"Outputs: bitrate reset: current {self.current_bitrate}, locked {self.bitrate_locked}")
        elif bitrate == "dec":
            new_idx = max(0, min(bitrate_idx + 1, len(self.bitrate_steps) - 1))
            self.current_bitrate = self.bitrate_steps[new_idx]
            self.bitrate_locked = True
            logging.debug(f"Outputs: bitrate decremented: current {self.current_bitrate}, locked {self.bitrate_locked}")
        elif bitrate == "inc":
            new_idx = max(0, min(bitrate_idx - 1, len(self.bitrate_steps) - 1))
            self.current_bitrate = self.bitrate_steps[new_idx]
            self.bitrate_locked = True
            logging.debug(f"Outputs: bitrate incremented: current {self.current_bitrate}, locked {self.bitrate_locked}")
        else:
            try:
                bitrate = int(json.loads(post_contents)["current_bitrate"])
                if bitrate in self.bitrate_steps:
                    self.current_bitrate = bitrate
                    res.status = falcon.HTTP_200
                    res.text = self.as_json()
                    logging.debug(f"Outputs: bitrate set.")
                else:
                    res.status = falcon.HTTP_400
                    res.text = json.dumps({"error": "bitrate not in bitrate_steps"}, ensure_ascii=False)
                    logging.warning(f"Outputs: bitrate not in bitrate_steps.")
            except Exception:
                res.text = json.dumps({"error": "invalid bitrate"}, ensure_ascii=False)
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
            logging.debug(f"SRT: blank stats.")
            pass
        censored_url = self.censor_url()
        doc = {
            "stats": self.stats,
            "output": censored_url,
            "message": str(self.srt_message)
        }

        logging.debug(f"SRT: get stats: {doc}.")

        res.text = json.dumps(doc, ensure_ascii=False)
        res.status = falcon.HTTP_200

    def censor_url(self, raw_url=None, mode="partial"):
        """
        Censors the SRT URL, in case the display might be shown. Leaking full connection info could be bad.
        Args:
            raw_url (str, optional): Uncensored url, if None, use this object's SRT URL. Defaults to None.
            mode (str, optional): Mode to censor the URL with. Defaults to "passphrase".
                "passphrase" replaces the passphrase with 4 *s.
                "full" replaces everything useful with ****s.
                "partial" replaces some useful information. This includes the passphrase, and most but not all the characters of the host.
                "none" does nothing, the full, uncensored URL.
        Returns
            (str): The censored version of the URL
        """
        if not raw_url:
            raw_url = self.srt_output.dst_conn
        if mode == "none":
            return raw_url
        if mode == "full":
            return "[REDACTED]"
        parsed = urllib.parse.urlsplit(raw_url)
        netloc = parsed.netloc
        scheme = parsed.scheme
        qs = urllib.parse.parse_qs(parsed.query)
        # All modes that aren't none censor the passphrase.
        qs["passphrase"] = "****"
        if mode == "partial":
            s = netloc.split('.')
            tld, port = s[-1].split(':')
            netloc = f"{s[0][ : 2]}****.{tld}:{port}"
        qs = urllib.parse.urlencode(qs, doseq=True).replace("%2A", '*')
        url_parts = (scheme, netloc, '', qs, '')
        new_url = urllib.parse.urlunsplit(url_parts)
        return new_url

class SRTLA(object):
    def __init__(self, srtla):
        self.srtla_output = srtla
        self.ip_addrs = self.get_ips()

    def get_ips(self):
        with open(self.srtla_output.ip_file, 'r') as f:
            raw = f.readlines()
        logging.debug(f"SRTLA: raw ips: {raw}")
        return [str(x.strip()) for x in raw]


    def on_get(self, req, res):
        doc = {
            "ip_list": self.ip_addrs
        }
        logging.debug("SRTLA: on_get ips.")
        res.text = json.dumps(doc, ensure_ascii=False)
        res.status = falcon.HTTP_200


class StreamOutput(object):
    def __init__(self, output_pipeline):
        self.output_pipeline = output_pipeline

    def on_post_play(self, req, res):
        self.output_pipeline.play()
        res.text = json.dumps({"message": "Stream playing."}, ensure_ascii=False)
        res.status = falcon.HTTP_200
        logging.debug(f"StreamOutput: Playing")

    def on_post_pause(self, req, res):
        self.output_pipeline.pause()
        res.text = json.dumps({"message": "Stream paused."}, ensure_ascii=False)
        res.status = falcon.HTTP_200
        logging.debug(f"StreamOutput: Paused")


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
        elif "unlock" in req.url:
            self.stream_remote.unlock_stream()
            msg = "Stream unlocked."

        logging.debug(f"StreamControls: on_post result: {msg}")

        res.text = json.dumps({"message": msg}, ensure_ascii=False)
        res.status = falcon.HTTP_200

    def on_get(self, req, res):
        status = self.stream_remote.get_status()
        logging.debug(f"StreamControls: {status}")
        res.text = json.dumps(status, ensure_ascii=False)
        res.status = falcon.HTTP_200

class AudioControls(object):
    def __init__(self, output_pipe):
        self.output_pipe = output_pipe

    def on_get(self, req, res):
        active_audio = self.output_pipe.get_property("output1-audio", "listen-to")
        res.text = json.dumps({"active": active_audio, "muted": self.output_pipe.audio_mute, "total_inputs": 2}, ensure_ascii=False)
        logging.debug(f"AudioControls: active: {active_audio}, get results: {res.text}.")
        res.status = falcon.HTTP_200

    def on_post_mute(self, req, res):
        self.output_pipe.toggle_audio_mute()
        active_audio = self.output_pipe.get_property("output1-audio", "listen-to")
        res.text = json.dumps({"active": active_audio, "muted": self.output_pipe.audio_mute, "total_inputs": 2}, ensure_ascii=False)
        logging.debug(f"AudioControls: mute, active: {active_audio}, post results: {res.text}.")
        res.status = falcon.HTTP_200

    def on_post_name(self, req, res, input_name):
        print(f"Switch to input {input_name}.")
        self.output_pipe.switch_audio_src(input_name)
        active_audio = self.output_pipe.get_property("output1-audio", "listen-to")
        res.text = json.dumps({"active": active_audio, "muted": self.output_pipe.audio_mute, "total_inputs": 2}, ensure_ascii=False)
        logging.debug(f"AudioControls: name, active: {active_audio}, post results: {res.text}.")
        res.status = falcon.HTTP_200
