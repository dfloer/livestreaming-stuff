import netifaces
from control import read_config
from pathlib import Path

def find_ips(devs=[], exclude_lo=True):
    """[summary]

    Args:
        devs (list, optional): Devices to limit the search for IP addresses to. Defaults to [].
        exclude_lo (bool, optional): Exclude loopback. If lo in devs, include it. Defaults to True.
    Returns:
        [dict]: Dictionary of {"interface": ["ip addresses"]}.
    """
    ip_addrs = {}
    if not devs:
        devs = netifaces.interfaces()
    if exclude_lo:
        devs = [x for x in devs if x != "lo"]
    for x in devs:
        try:
            addrs = netifaces.ifaddresses(x)[2]
            ip_addrs[x] = [a["addr"] for a in addrs]
        except KeyError:
            pass
    print(f"find_ips: ip_addrs {ip_addrs}")
    return ip_addrs


def srtla_ip_setup(file_path="srtla_ips.txt"):
    """
    Make sure there's a file with IP addresses to pass to SRTLA.
    If the file exists, this will overwrite it.
    Args:
        file_path (Path, oprional): Path where we should create the temporary file. Defaults to "srtla_ips.txt" in the current dir.
    Returns:
        [Path]: Path to the ip address file to pass to SRTLA.
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
    return output_path
