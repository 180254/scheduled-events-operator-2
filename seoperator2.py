#!/usr/bin/python3 -u
import copy
import datetime
import json
import os
import pickle
import signal
import socket
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, TypeVar, Generic, List, Dict

T = TypeVar("T")


class Cacheable(Generic[T]):
    def __init__(self, cache_dir: str) -> None:
        super().__init__()
        self.cache_dir: str = cache_dir
        self.cache_enabled: bool = os.path.isdir(cache_dir)

    def _cache_read(self, key: str, default_value: T) -> T:
        if not self.cache_enabled:
            return default_value

        cache_file = os.path.join(self.cache_dir, key)
        try:
            with open(cache_file, "rb") as handle:
                return pickle.load(handle)
        except (OSError, IOError):
            return default_value

    def _cache_write(self, key: str, value: T) -> None:
        if not self.cache_enabled:
            pass

        cache_file = os.path.join(self.cache_dir, key)
        with open(cache_file, "wb") as handle:
            pickle.dump(value, handle)
        pass


class CacheableList(Cacheable[T]):
    def __init__(self, cache_dir: str, name: str):
        super().__init__(cache_dir)
        self._name: str = name
        self._list: List[T] = super()._cache_read(name, [])

    def values(self) -> List[T]:
        return copy.copy(self._list)

    def len(self) -> int:
        return len(self._list)

    def append(self, value: T) -> None:
        self._list.append(value)
        self._cache_write(self._name, self._list)

    def remove(self, value: T) -> None:
        self._list.remove(value)
        self._cache_write(self._name, self._list)


class Context(object):
    def __init__(self, config_file_path: str, cache_dir: str):
        self.config_file_path: str = config_file_path
        self.cache_dir = cache_dir

        config_data = read_config_file(config_file_path)

        self.api_metadata_instance_url: str = \
            config_data.get("api-metadata-instance-url",
                            "http://169.254.169.254/metadata/scheduledevents?api-version=2019-08-01")
        self.api_metadata_scheduledevents_url: str = \
            config_data.get("api-metadata-scheduledevents-url",
                            "http://169.254.169.254/metadata/instance?api-version=2020-09-01")

        self.main_loop_rate: int = config_data.get("main-loop-rate", 60)
        self.socket_timeout: int = config_data.get("socket-timeout", 10)
        self.ignored_event_types: List[str] = config_data.get("ignored-event-types", [])
        self.kubectl_drain_options: List[str] = config_data.get("kubectl-drain-options", [])

        self.this_hostnames: Dict[str, str] = get_this_hostnames(self)
        self.exit_threading_event: threading.Event = threading.Event()

        self.already_processed_events: CacheableList[str] = \
            CacheableList[str](self.cache_dir, "already_processed_events")
        self.kubectl_cordon_cache: CacheableList[str] = \
            CacheableList[str](self.cache_dir, "kubectl_cordon_cache")

    def serialize(self) -> Dict[str, Any]:
        return {
            "config_file_path": self.config_file_path,
            "api_metadata_instance_url": self.api_metadata_instance_url,
            "api_metadata_scheduledevents_url": self.api_metadata_scheduledevents_url,
            "cache_dir": self.cache_dir,
            "main_loop_rate": self.main_loop_rate,
            "socket_timeout": self.socket_timeout,
            "ignored_event_types": self.ignored_event_types,
            "kubectl_drain_options": self.kubectl_drain_options,
            "this_hostnames": self.this_hostnames,
            "exit_threading_event": self.exit_threading_event.is_set(),
            "already_processed_events": self.already_processed_events.values(),
            "kubectl_cordon_cache": self.kubectl_cordon_cache.values()
        }


def read_config_file(config_file_path: str) -> Dict[str, Any]:
    config_data = {}
    if os.path.isfile(config_file_path):
        with open(config_file_path) as f:
            config_data = json.load(f)
    return config_data


def print_(message: str, **kwargs) -> None:
    timestamp = datetime.datetime.utcnow().astimezone().replace(microsecond=0).isoformat()
    print(json.dumps({"timestamp": timestamp, "message": message, **kwargs}), flush=True)


def subprocess_stdout_reader(cmd: List[str], eventid: str, proc: subprocess.Popen) -> None:
    subprocess_id = " ".join(cmd)
    for message in proc.stdout:
        print_(message, eventid=eventid, subprocess=subprocess_id)


def subprocess_run(cmd: List[str], eventid: str) -> None:
    print_(f"Running a command: {cmd} for {eventid}.", eventid=eventid)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    proc_output_reader = threading.Thread(target=subprocess_stdout_reader, args=(cmd, eventid, proc))
    proc_output_reader.start()
    proc.wait()


def b36_encode(num: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while not result or num > 0:
        num, i = divmod(num, 36)
        result = digits[i] + result
    return result


# example
#   input: aks-default-36328368-vmss_18
#   output: aks-default-36328368-vmss00000i
def compute_name_to_node_name(compute_name: str) -> str:
    name_prefix, vm_index_base10 = compute_name.split("_")
    vm_index_base36 = b36_encode(int(vm_index_base10))
    return name_prefix + vm_index_base36.rjust(6, "0")


def get_this_hostnames(context: Context) -> Dict[str, str]:
    request = urllib.request.Request(context.api_metadata_instance_url)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=context.socket_timeout) as response:
        metadata_instance = json.loads(response.read())
        compute_name = metadata_instance.get("compute").get("name")
        return {
            "hostname": socket.gethostname(),
            "computename": compute_name,
            "nodename": compute_name_to_node_name(compute_name),
        }


def get_scheduled_events(context: Context) -> Dict[str, Any]:
    request = urllib.request.Request(context.api_metadata_scheduledevents_url)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=context.socket_timeout) as response:
        metadata_scheduledevents = json.loads(response.read())
        return metadata_scheduledevents


def start_scheduled_event(context: Context, eventid: str) -> Any:
    print_(f"Starting scheduled event.", eventid=eventid)

    # give some time to external monitoring to collect logs
    if context.exit_threading_event.wait(5):
        return

    data = {"StartRequests": [{"EventId": eventid}]}
    databytes = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(context.api_metadata_scheduledevents_url, data=databytes)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=context.socket_timeout) as response:
        return response.read()


def handle_scheduled_events(context: Context, scheduled_events: Dict[str, Any]) -> None:
    events = scheduled_events["Events"]

    # uncordon nodes affected by scheduled events in the past
    if context.kubectl_cordon_cache.len() > 0:
        for nodename in context.kubectl_cordon_cache.values():
            event_affecting_node_found = False
            for event in events:
                if nodename in event["Resources"]:
                    event_affecting_node_found = True
                    break
            if not event_affecting_node_found:
                kubectl_uncordon(context, "null", nodename)

    if len(events) == 0:
        return

    print_(f"Current list of planned events.", events=events)

    for event in events:
        eventid = event["EventId"]
        eventstatus = event["EventStatus"]
        resources = event["Resources"]
        eventtype = event["EventType"]
        # resourcetype = event["ResourceType"]
        # notbefore = event["NotBefore"]

        if eventid in context.already_processed_events.values():
            continue

        print_(f"A new event was found {eventid} ({eventtype}).", eventid=eventid)
        if eventstatus == "Scheduled" \
                and context.this_hostnames["computename"] in resources \
                and eventtype not in context.ignored_event_types:
            print_(f"Handling the event {eventid}.", eventid=eventid)
            handle_scheduled_event(context, eventid)
            print_(f"Handled the event {eventid}.", eventid=eventid)
        else:
            print_(f"Skipping the event {eventid}.", eventid=eventid)

        context.already_processed_events.append(eventid)


def handle_scheduled_event(context: Context, eventid: str) -> None:
    nodename = context.this_hostnames["nodename"]
    kubectl_cordon(context, eventid, nodename)
    kubectl_drain(context, eventid, nodename)
    start_scheduled_event(context, eventid)


def kubectl_cordon(context: Context, eventid: str, nodename: str) -> None:
    subprocess_run(["kubectl", "cordon", nodename], eventid)
    context.kubectl_cordon_cache.append(nodename)


def kubectl_drain(context: Context, eventid: str, nodename: str) -> None:
    subprocess_run(["kubectl", "drain", nodename] + context.kubectl_drain_options, eventid)


def kubectl_uncordon(context: Context, eventid: str, nodename: str) -> None:
    subprocess_run(["kubectl", "uncordon", nodename], eventid)
    context.kubectl_cordon_cache.remove(nodename)


def the_end(context: Context, signal_number: Any):
    print_(f"Interrupted by signal {signal_number}, shutting down.")
    context.exit_threading_event.set()


def main():
    try:
        print_("The operator started to work.")

        for some_signal in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
            signal.signal(some_signal,
                          lambda signal_number, current_stack_frame:
                          the_end(context, signal_number))

        config_file_path = sys.argv[1] if len(sys.argv) > 1 else "/just/not/exist"
        cache_dir = sys.argv[2] if len(sys.argv) > 2 else "/just/not/exist"

        context = Context(config_file_path, cache_dir)
        print_(f"The configuration is loaded.", context=context.serialize())

        while True:
            print_("The program is still running.")
            data = get_scheduled_events(context)
            handle_scheduled_events(context, data)
            if context.exit_threading_event.wait(context.main_loop_rate):
                break

    except Exception:
        traceback_formatted = str(traceback.format_exc())
        print_("Fatal error in the main loop.", traceback=traceback_formatted)
        sys.exit(1)


if __name__ == "__main__":
    main()
