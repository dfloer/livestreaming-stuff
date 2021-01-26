import toml

from control import read_config

_config = read_config()["api_server"]
bind = f"{_config['address']}:{_config['port']}"
if _config["debug"]:
    log_level = "debug"