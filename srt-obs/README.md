# Bad connection detection and remote control for OBS

## Overview

Streaming from the field can be fraught with connectivity issues. So we use OBS on a computer connected with a reliable connection to the streaming service ingest. This is also needed for services that support legacy RTMP/h.264, with a transmux & transcode happening.

This part uses Gunicorn and Falcon for the API server, `srt-live-transmit` for the stats with the [obs-websocket](https://github.com/Palakis/obs-websocket) plugin and the [obs-websocket-py](https://github.com/Elektordi/) bindings. This has only been tested on Linux, but windows should probably work.

- `srt-obs-switcher.py` can be used standalone as is.
- However, there's also a gunicorn based REST API for control from the web page running from the Jetson Nano.

## Dependencies

- `srt-live-transmit` executable needs to be available in the PATH.
- `obs-websocket` plugin needs to be installed, active and configured.
- The rest of the dependencies can be pulled in using pipenv.

## Setup & configuration

Configuration is stored in `srt_config.toml`. Most of the options are documented there with comments, but most settings aren't going to need to be changed from the defaults.

- Make sure to set a hard to guess api-key. If none is specified, a temporary one will be created each run and displayed in the console. This needs to **exactly** match the one on the sender sider.
- API communication is over SSL. This means that SSL certificates need to be generated or obtained. Default location is the `ssl/` subdirectory. Cert generation isn't covered by this doc at this time.
- Scene setup in OBS is not automatic, nor are any other settings. The default names for the scenes are "IRL Input" and "BRB" for the normal and brb scenes. If the names are different, update them in the config file.
- Default ingest of the stream is over SRT on UDP port 4000 with the control API on port 4443. These will need to be forwarded through a firewall. These ports can be changed in the config.
- OBS needs to connect an SRT source on this host, port 9000. VLC may work better than media source.
- As SRT is explosed to the Internet, encryption is mandatory. This means that the SRT passphrase must be **exactly** the same here as on the Jetson. If they don't match, it won't work, and there isn't currently any good error checking.
- Other settings, especially the drop thresholds, will likely need to be adjusted based on general network conditions.

## Running

`gunicorn -b 0.0.0.0:4443 remote_control --certfile=ssl/ssl.crt --keyfile=ssl/ssl.key`

- gunicorn debugging can be enabled by adding `--log-level debug`.
- The port `:4443` needs to be the same as is specified on the Nano side.

Eventually it'd be nice if startup was cleaner, and check some common error cases, etc, but that hadn't happened yet.
