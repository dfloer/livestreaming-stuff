import toml
from loguru import logger as logging
import sys



def get_config(config_file="srt_config.toml"):
    with open(config_file, 'r') as f:
        return toml.load(f)


def get_log_level(log_level="info"):
    log_map = {10: "debug", 20: "info", 30: "warning", 40: "error"}
    return log_map.get(log_level, "info")

def configure_logging(log_level="info"):
    # Make loguru behave like logging, and use gunicorn's log level.
    logging.remove()
    log_level = get_log_level(log_level)
    logging.add(sys.stderr, level=log_level.upper())
    print(f"Logging started with log level: {log_level.upper()}.")
