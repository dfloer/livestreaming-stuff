# livestreaming-stuff

Run with `gunicorn -b 0.0.0.0:8000 app`. Port can be changed to something other than 8000. To connect the webapp, browse to `http://IP/name:8000/static/index.html`.

For SSL to work to connect to the server, make sure PEM formatted public key is in the `/ssl` directory. The api_key and srt_passphrase in the config need to **exactly** match the ones on the server.

## Dependencies

- gst-interpipe
- gstd
- srt
- pyalsaaudio
  - This currently needs to be the system as the one on PyPi doesn't work with the verion of Python on the Jetson OS image.
- Python dependencies are installed using pipenv: `pipenv install`.

## Notes

While an eventual goal is to support arbitrary capture devices, the project has only been tested with a couple. As such, things may be hardcoded in places they shouldn't be. However, the project is structured in such a way to make hardcoding easier to remove.

- Presently there are hard timestamps and bitrate indicators burned into the video. These aren't configurably removable at present, but that'll likely get added soon.
- The Camlink 4k shuts off after it has had no signal, causing it to get lost from gstreamer. There isn't a good workaround now, other than not removing an HDMI signal from it.
- The Jetson Nano seems to have an issue decoding an h264 stream and encoding it to HEVC while another capture device is running. Or it could be the first capture device's encoder. Either way, this has caused a lot of minor visual glitches in testing that haven't been ironed out yet.
- There's currently no way to set audio delay, but pipelines were created with this in mind so that delay for sync could be added.
- There isn't yes support for non-HDMI audio sources, but adding a microphone in (e.g. a lav or shotgun) is likely to happen.
- While audio volume can be changed using the API, there isn't anything in the webapp to adjust this (yet, probably).
- There aren't Ubuntu packages for gst-interpipe and gstd, these will need to be built manually form source.
