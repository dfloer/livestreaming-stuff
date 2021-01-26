# livestreaming-stuff

The initial goals for this part is to be able to capture 2 1080p30/60 streams from HDMI -> USB adapters and switch between them, including audio switching.

The stream is then sent to a computer running OBS using HEVC/SRT where another process watches the incoming SRT stream for issues, and if things get too bad, it switches to a BRB scene, and back when things have improved.

Controlling all of this is a webapp intended to run on a phone, that allows control of the system. Inputs, both audio and video independently, can be switched between, the bitrate can be changed, audio can be muted and the stream can be started and stopped, as well as stats and other status are displayed.

This relied on two API servers, one running on the Jetson for control of the encoder side of things, and one on the remote computer, where it provides simple controls for OBS.

## Status

This is Alpha level software is missing some important features, such as:

- bonding
- proper tests
- there are lots of hardcoded things that should be user configurable, but aren't presently.

## Project Parts

### Jetson Nano

This handles everything on the Jetson Nano and is in the `/api` subfolder of this project. See the readme there for more information.

### OBS Computer

This handled everything on the computer running OBS and is in the `/srt-obs` subfolder of this project. See the readme there for more information.

Note that OBS and this part do not need to be running on the same computer. This can be run on a RPi, controlling OBS on a more powerful computer. All it needs to be able to do is contact that computer using the obs-websocket plugin.
