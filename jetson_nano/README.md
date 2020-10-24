# Jetson Nano Livestreaming

Software used to livestream on the Jetson Nano.

## Overview

- `gstd_streaming.py` Basic wrapper program using the Python binding to RidgeRun's [https://github.com/RidgeRun/gstd-1.x.git](gstd) and using their [https://github.com/RidgeRun/gst-interpipe](GstInterpipe) library. Output to a (hardcoded right now) UDP listener over HEVC/MPEG-TS.
- `test_gstd` Creates a test video file in /tmp. HEVC encoded with a switch between inputs and bitrate dynamically changing.
- `jetson_nano_2camera_test.py` Tests switching two inputs, one a Avermedia GC311 (with hardware H264 encoder) and one a Elgato Camlink 4k. Also changes bitrate dynamically.Output to a (hardcoded right now) UDP listener over HEVC/MPEG-TS.
    - The Camlink 4k has a colour space related bug, and the workaround in, somewhat counter-intuitively, to perform a conversion on the non-Camlink input.
