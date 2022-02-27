import remote_control
from utils import get_config, get_log_level

_cfg =  get_config()
_api_cfg = _cfg["api"]



bind = _api_cfg["listen"]
workers = 4
loglevel = get_log_level(_cfg["logging"]["log_level"].lower())
_ssl_path = _api_cfg["ssl_path"]
certfile = f"{_ssl_path}/ssl.crt"
keyfile = f"{_ssl_path}/ssl.key"

# Server Hooks
on_exit = remote_control.on_exit