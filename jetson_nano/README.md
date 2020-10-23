# Jetson Nano Livestreaming

Software used to livestream on the Jetson Nano.

## Overview

- `gstd_streaming.py` Basic wrapper program using the Python binding to RidgeRun's [https://github.com/RidgeRun/gstd-1.x.git](gstd) and using their [https://github.com/RidgeRun/gst-interpipe](GstInterpipe) library.
- `test_gstd` Creates a test video file in /tmp. HEVC encoded with a switch between inputs and bitrate dynamically changing.
