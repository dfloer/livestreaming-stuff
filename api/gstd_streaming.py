from pygstc.gstc import *
from dataclasses import dataclass
from datetime import datetime

@dataclass(init=False)
class Pipeline(object):
    client: GstdClient
    name: str
    nice_name: str
    description: str
    debug: bool
    def __init__(self, gstdclient, name, config, debug=False):
        self.client = gstdclient
        self.name = name
        self.nice_name = config["nice_name"]
        self.description = config["full_gst"]
        self.debug = debug

        if self.debug:
            self.print_debug(f"Pipeline created: {self.name}")
        self.client.pipeline_create(self.name, self.description)

    def play(self):
        if self.debug:
            self.print_debug(f"Pipeline playing: {self.name}")
        self.client.pipeline_play(self.name)

    def pause(self):
        if self.debug:
            self.print_debug(f"Pipeline paused: {self.name}")
        self.client.pipeline_pause(self.name)

    def stop(self):
        if self.debug:
            self.print_debug(f"Pipeline stopped: {self.name}")
        self.client.pipeline_stop(self.name)

    def delete(self):
        if self.debug:
            self.print_debug(f"Pipeline deleted: {self.name}")
        self.client.pipeline_delete(self.name)

    def eos(self):
        if self.debug:
            self.print_debug(f"Pipeline end of stream: {self.name}")
        self.client.event_eos(self.name)

    def list_elements(self):
        elements = self.client.list_elements(self.name)
        if self.debug:
            self.print_debug(f"{self.name} elements: {elements}")
        return elements

    def set_property(self, element, prop, val):
        new_val = str(val)
        if self.debug:
            self.print_debug(f"{self.name} element {element}: {prop} = {new_val}.")
        self.client.element_set(self.name, element, prop, new_val)

    def cleanup(self):
        self.eos()
        self.stop()
        self.delete()
        if self.debug:
            self.print_debug(f"Pipeline cleaned up: {self.name}")

    def print_debug(self, msg):
        print(f"[{datetime.now()}] {msg}")

    def get_status(self):
        status = self.client.read(f"/pipelines/{self.name}/state")["value"]
        if self.debug:
            self.print_debug(f"Pipeline {self.name}: {status}")

@dataclass(init=False)
class Output(Pipeline):
    encoder: str
    url: str
    bitrate: int
    fallback_bitrates: list
    def __init__(self, gstdclient, name, config, encoder_config, debug=False):
        self.encoder = ''
        self.bitrate = encoder_config["preferred_bitrate"]
        self.fallback_bitrates = encoder_config["fallback_bitrates"]
        self.url = config["url"]
        super().__init__(gstdclient, name, config, debug)

    def switch_src(self, new_src):
        if self.debug:
            self.print_debug(f"Switching pipeline: {self.name} to source {new_src}")
        self.client.element_set(self.name, self.name, 'listen-to', new_src)

    def set_bitrate(self, val=0):
        if not val:
            val = self.bitrate
        new_val = str(val)
        if self.debug:
            self.print_debug(f"{self.name} encoder '{self.encoder}' bitrate changed to {new_val}.")
        self.client.element_set(self.name, self.encoder, "bitrate", new_val)
        text_elem_name = [x["name"] for x in self.list_elements() if "textoverlay" in x["name"]][0]
        self.set_property(text_elem_name, "text", f"bitrate: {self.bitrate / 1000}kb/s")