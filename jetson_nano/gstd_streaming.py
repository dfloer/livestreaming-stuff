from pygstc.gstc import *
from dataclasses import dataclass
from datetime import datetime

@dataclass(init=False)
class Pipeline(object):
    client: GstdClient
    name: str
    description: str
    debug: bool
    def __init__(self, gstdclient, name, description='', debug=False):
        self.client = gstdclient
        self.name = name
        self.description = description
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

    def switch_src(self, new_src):
        if self.debug:
            self.print_debug(f"Switching pipeline: {self.name} to source {new_src}")
        self.client.element_set(self.name, self.name, 'listen-to', new_src)

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


# class HEVCEncoder(Pipeline):
    # def __init__(self, encoder):
        # self.encoder = encoder

    def set_bitrate(self, encoder, val):
        new_val = str(val)
        if self.debug:
            self.print_debug(f"{self.name} encoder '{encoder}' bitrate changed to {new_val}.")
        self.client.element_set(self.name, encoder, "bitrate", new_val)

