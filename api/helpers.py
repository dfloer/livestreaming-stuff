import netifaces
from control import read_config
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def find_ips(devs=[], exclude_lo=True):
    """
    Args:
        devs (list, optional): Devices to limit the search for IP addresses to. Defaults to [].
        exclude_lo (bool, optional): Exclude loopback. If lo in devs, include it. Defaults to True.
    Returns:
        [dict]: Dictionary of {"interface": ["ip addresses"]}.
    """
    ip_addrs = defaultdict(list)
    if not devs:
        devs = netifaces.interfaces()
    if exclude_lo:
        devs = [x for x in devs if x != "lo"]
    for x in devs:
        try:
            addrs = netifaces.ifaddresses(x)[2]
            for a in addrs:
                ip_addr = a["addr"]
                if "169.254" not in ip_addr:  # Want to ignore addresses of 169.254.x.x (automatic private) because they won't work.
                    ip_addrs[x] += [ip_addr]
        except KeyError:
            pass  # No key 2, which is IPv4 addresses.
        except ValueError:
            pass  # If devs contains an interface that isn't part of the system.
    print(f"find_ips: ip_addrs {ip_addrs}")
    return ip_addrs


def srtla_ip_setup(file_path="srtla_ips.txt"):
    """
    Make sure there's a file with IP addresses to pass to SRTLA.
    If the file exists, this will overwrite it.
    Args:
        file_path (Path, oprional): Path where we should create the temporary file. Defaults to "srtla_ips.txt" in the current dir.
    Returns:
        (Path): Path to the ip address file to pass to SRTLA.
        (dict): the IP address dictionary
    """
    config = read_config()["srtla_config"]
    output_path = Path(config["srtla_ip_path"])
    print("output_path:", output_path)
    if not config["srtla_ip_path"]:
        output_path = Path(file_path)
        ip_addrs = find_ips(devs=config["srtla_devices"])
        with open (output_path, 'w') as f:
            for row in ip_addrs.values():
                for ip in row:
                    f.write(f"{ip}\n")
    return output_path, ip_addrs

def timestamp():
    pass