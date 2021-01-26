from pygstc.gstc import *
from dataclasses import dataclass
from datetime import datetime
from pygstc.gstcerror import GstdError

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
        self.create_pipeline()

    def create_pipeline(self):
        """
        This is mostly meant for crash recovery, but if gstd already has the pipeline that we're trying to create, just use the existing one.
        If there was anything else using gstd, this could be problematic, but there isn't, so this is fine.

        There _may_ be a bug in gstd where if we try to re-create an existing pipeline and get an error, the pipeline gets into a weird state.
        So instead of a try/except block, explicitly check to see if this pipeline already exists.
        """
        existing_pipelines = [x["name"] for x in self.client.list_pipelines()]
        if self.name not in existing_pipelines:
            if self.debug:
                self.print_debug(f"Pipeline created: {self.name}")
            self.client.pipeline_create(self.name, self.description)
        else:
            if self.debug:
                self.print_debug(f"Existing pipeline re-used: {self.name}")

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
            self.print_debug(f"{self.name} element {element}: {prop} set to {new_val}.")
        self.client.element_set(self.name, element, prop, new_val)

    def get_property(self, element, prop):
        val = self.client.element_get(self.name, element, prop)
        if self.debug:
            self.print_debug(f"{self.name} element {element}: {prop} is {val}.")
        return str(val)

    def cleanup(self):
        self.eos()
        self.stop()
        self.delete()
        if self.debug:
            self.print_debug(f"Pipeline cleaned up: {self.name}")

    @property
    def state(self):
        return self.client.read(f"pipelines/{self.name}/state")['value']

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
    url: str
    audio_mute: bool
    volume_element: str
    def __init__(self, gstdclient, name, config, encoder_config, debug=False):
        self.encoder = ''
        self.bitrate = encoder_config["preferred_bitrate"]
        self.fallback_bitrates = encoder_config["fallback_bitrates"]
        self.url = config["url"]
        self.audio_mute = False
        super().__init__(gstdclient, name, config, debug)
        self.volume_element = [x['name'] for x in self.list_elements() if "volume" in x['name']][0]

    def switch_src(self, new_src):
        new_src = new_src + "-video"
        if self.debug:
            self.print_debug(f"Switching pipeline: {self.name} to source {new_src}")
        self.set_property(self.name, 'listen-to', new_src)

    def set_bitrate(self, val=0):
        if not val:
            val = self.bitrate
        new_val = str(val)
        if self.debug:
            self.print_debug(f"{self.name} encoder '{self.encoder}' bitrate changed to {new_val}.")
        self.client.element_set(self.name, self.encoder, "bitrate", new_val)
        text_elem_name = [x["name"] for x in self.list_elements() if "textoverlay" in x["name"]][0]
        self.set_property(text_elem_name, "text", f"bitrate: {val / 1000}kb/s")

    def toggle_audio_mute(self):
        """
        Toggle the muting of the audio. If muted, unmute. It unmuted, mute.
        """
        self.audio_mute = not self.audio_mute
        if self.debug:
            self.print_debug(f"Audio mute status: {self.audio_mute}")
        self.set_property(self.volume_element, "mute", self.audio_mute)

    def set_volume(self, volume):
        """
        Set the audio output volume.
        Args:
            volume (float): Volume level to set. 0=0%, 1.0=100%. Volumes higher than 1.0 work (up to 10.0 or so) but are amplification.
        """
        if self.debug:
            self.print_debug(f"Volume set to : {volume}")
        self.set_property(self.volume_element, "mute", self.audio_mute)


    def switch_audio_src(self, new_src):
        """
        Switch to the given audio source/
        Args:
            new_src (str): Name of the input to switch to. Does not need the "-audio".
        """
        new_src = new_src + "-audio"
        if self.debug:
            self.print_debug(f"Switching audio: {self.name} to source {new_src}")
        self.set_property(self.name + "-audio", 'listen-to', new_src)
