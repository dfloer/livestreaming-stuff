import os
import secrets
import subprocess
import sys
import threading
import time
import toml
from datetime import datetime
from loguru import logger as logging


def get_config(config_file="srt_config.toml"):
    with open(config_file, "r") as f:
        return toml.load(f)


def get_log_level(log_level="info"):
    log_map = {10: "debug", 20: "info", 30: "warning", 40: "error"}
    log_level = log_map.get(log_level, "info") if log_level not in log_map.values() else log_level
    return log_level


def configure_logging(log_level="info"):
    # Make loguru behave like logging, and use gunicorn's log level.
    logging.remove()
    log_level = get_log_level(log_level)
    logging.add(sys.stderr, level=log_level.upper())
    print(f"Logging started with log level: {log_level.upper()}.")


def generate_passphrase(length=32):
    """
    Generates a passphrase for use with SRT.
    Args:
        length (int, optional): Length of the passphrase to generate. Default 32.
    Returns:
        (str) the passphrase.
    """
    return secrets.token_hex(length)


def get_passphrase(passphrase=""):
    """
    Prints, or generates, a passphrase as needed
    Args:
        passphrase (str, optional): Passphrase to set. Defaults to ''.
    Returns:
        str: passphrase, either a generated one or the one passed in as an argument.
    """
    if not passphrase:
        logging.debug("Generated SRT passphrase.")
        passphrase = generate_passphrase()
    # This is explicitly printed, and not logged, so that the passphrase doesn't show up in logs normally.
    div = "----------------------------------------------------------------"
    print(f"\nSRT Passphrase:")
    print(div)
    print(f"{passphrase}")
    print(div)
    return passphrase


def generate_api_key(cfg, key_len=32):
    api_key = cfg["api"]["api_key"]
    if not api_key:
        return secrets.token_urlsafe(key_len)
    return api_key


class ThreadManager(threading.Thread):
    def __init__(self, name=""):
        super().__init__()
        self._pid = None
        self._pgid = None
        self._process = None
        self.start_time = None
        self.name = name
        self.event = threading.Event()
        self.wait_interval = 0.001
        self.cmd = ""
        

    def start_process(self, blocking=False):
        """
        Start the process with the given command.
        Args:
            cmd (string): Command strings, as would be passed into a shell.
            blocking (bool, optional): True if the processes output should be blocking, false otherwise. Defaults to False.
        """
        logging.info(f"{self.name}: Process starting with command: {self.cmd}.")
        self._process = subprocess.Popen(
            f"{self.cmd}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        self._pid = self._process.pid
        self._pgid = os.getpgid(self._pid)
        logging.warning(
            f"{self.name}: Process stared, pid={self._pid}, pgid={self._pgid}."
        )
        self.start_time = datetime.now()
        os.set_blocking(self._process.stdout.fileno(), blocking)

    def stop(self):
        """
        Stops the process and the run-loop.
        """
        self.kill_process()
        self.event.set()
        logging.info(f"{self.name}: Process stopped.")

    def kill_process(self):
        """
        Kills the process spawned.
        """
        logging.warning(f"{self.name}: Killing process with pid={self._pid}.")
        self._process.terminate()

    def run(self):
        """
        Loop to run in this thread.
        Note that in order to do anything, the run_inner() function needs to be overridded in a subclass.
        """
        logging.warning(f"{self.name}: run thread started.")
        while not self.event.is_set():
            self.run_inner()
            self.event.wait(self.wait_interval)

    def restart_process(self, wait_time=1.0):
        """
        Restarts a process. The wait_time parameter is useful if there's an issue restarting a process immediately after it's killed.
        Args:
            wait_time (float, optional): Time, in seconds, to wait before the process restarts. Defaults to 1.0.
        """
        logging.warning(f"{self.name}: Process restarted.")
        self.kill_process()
        self.tsleep(wait_time)
        self.start_process()

    def tsleep(self, t):
        """
        Thread-aware sleep for t seconds.
        Args:
            t (float): Time to sleep, in seconds.
        """
        logging.debug(f"{self.name}: tsleep for {t}s.")
        threading.Timer(t, self.tsleep, kwargs={"t": t}).start()
        time.sleep(t)

    def run_inner():
        logging.error(f"Override run_inner() in subclass.")

    def read(self):
        return self._process.stdout.read()

    def readline(self):
        return self._process.stdout.readline()
