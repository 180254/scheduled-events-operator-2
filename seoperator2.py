#!/usr/bin/python3 -u
import abc
import datetime
import email.utils
import json
import os
import pickle
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, TypeVar, Generic, List, Iterator, Iterable, Dict

T = TypeVar("T")


# Serialize arbitrary Python objects to JSON.
# Fixes: TypeError: Object of type Xyz is not JSON serializable
# Fix consists of JsonSerializable, JsonSerializableEncoder.
class JsonSerializable(abc.ABC):

    @abc.abstractmethod
    def to_json(self) -> Any:
        pass


# Take a look at the documentation of JsonSerializable.
class JsonSerializableEncoder(json.JSONEncoder):

    def default(self, o: Any):
        if isinstance(o, JsonSerializable):
            return o.to_json()
        return json.JSONEncoder.default(self, o)


# print in a version that produces output containing json.
def print_(message: str, **kwargs) -> None:
    timestamp = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    print(json.dumps({"timestamp": timestamp, "message": message, **kwargs}, cls=JsonSerializableEncoder), flush=True)


# An interface that provides methods to "cache" (save) state.
# The state is stored on disk, under the specified key.
class Cacheable(Generic[T], object):

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


# A list that saves the state to disk with each change.
# The list recreates its last state in the constructor, so it is immune to container restarts.
class CacheableList(Cacheable[T], Iterable[T], JsonSerializable, object):

    def __init__(self, cache_dir: str, name: str) -> None:
        super().__init__(cache_dir)
        self._name: str = name
        self._list: List[T] = super()._cache_read(name, [])

    def append(self, value: T) -> None:
        self._list.append(value)
        self._cache_write(self._name, self._list)

    def remove(self, value: T) -> None:
        self._list.remove(value)
        self._cache_write(self._name, self._list)

    def __len__(self) -> int:
        return len(self._list)

    def __iter__(self) -> Iterator[T]:
        return iter(self._list)

    def __str__(self) -> str:
        return f"{self._list!s}"

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"{self._name!r}, {self._list!r})")

    def to_json(self) -> List[T]:
        return self._list


# This class has easily accessible information about the name of the VM on which this script is running.
# The "Azure Instance Metadata Service (Linux)" is helpful.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/instance-metadata-service?tabs=linux
class ThisHostnames(JsonSerializable, object):

    def __init__(self, api_metadata_instance: str, socket_timeout_seconds: int) -> None:
        request = urllib.request.Request(api_metadata_instance)
        request.add_header("Metadata", "true")
        with urllib.request.urlopen(request, timeout=socket_timeout_seconds) as response:
            metadata_instance = json.loads(response.read())
            self.hostname = socket.gethostname()
            self.compute_name = metadata_instance.get("compute").get("name")
            self.node_name = self._compute_name_to_node_name(self.compute_name)

    # example
    #   input: aks-default-36328368-vmss_18
    #   output: aks-default-36328368-vmss00000i
    @staticmethod
    def _compute_name_to_node_name(compute_name: str) -> str:
        name_prefix, vm_index_base10 = compute_name.split("_")
        vm_index_base36 = ThisHostnames._b36_encode(int(vm_index_base10))
        return name_prefix + vm_index_base36.rjust(6, "0")

    @staticmethod
    def _b36_encode(num: int) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        result = ""
        while not result or num > 0:
            num, i = divmod(num, 36)
            result = digits[i] + result
        return result

    def __str__(self) -> str:
        return f"{self.hostname!r}, {self.compute_name!r}, {self.node_name!r})"

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"{self.hostname!r}, {self.compute_name!r}, {self.node_name!r})")

    def to_json(self) -> Dict[str, Any]:
        return {
            "hostname": self.hostname,
            "compute_name": self.compute_name,
            "node_name": self.node_name,
        }


# An object-oriented representation of a single "scheduled event".
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
class ScheduledEvent(JsonSerializable, object):

    def __init__(self, event: Dict[str, Any]) -> None:
        super().__init__()
        self._raw: Dict[str, Any] = event
        self.eventid: str = event.get("EventId")
        self.eventtype: str = event.get("EventType")
        self.resourcetype: str = event.get("ResourceType")
        self.resources: List[str] = event.get("Resources")
        self.eventstatus: str = event.get("EventStatus")
        self.notbefore: datetime = self._parsedate_to_datetime(event.get("NotBefore"))
        self.description: str = event.get("Description")
        self.eventsource: str = event.get("EventSource")

    @staticmethod
    # https://bugs.python.org/issue30681
    def _parsedate_to_datetime(value) -> datetime:
        try:
            return email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None

    def __str__(self) -> str:
        return str(self._raw)

    def __repr__(self) -> str:
        return repr(self._raw)

    def to_json(self) -> Dict[str, Any]:
        return self._raw


# An object-oriented representation of a whole "scheduled events" response.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
class ScheduledEvents(Iterable[ScheduledEvent], JsonSerializable, object):

    def __init__(self, events: Dict[str, Any]) -> None:
        super().__init__()
        self._raw: Dict[str, Any] = events
        self.document_incarnation: int = events.get("DocumentIncarnation")
        self.events: List[ScheduledEvent] = list(map(ScheduledEvent, events.get("Events", [])))

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[ScheduledEvent]:
        return iter(self.events)

    def __str__(self) -> str:
        return str(self._raw)

    def __repr__(self) -> str:
        return repr(self._raw)

    def to_json(self) -> Dict[str, Any]:
        return self._raw


# A tool to perform operations on the "scheduled events" API.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#start-an-event
class ScheduledEventsManager(object):

    def __init__(self,
                 api_metadata_scheduledevents: str,
                 socket_timeout_seconds: int,
                 delay_before_program_close_seconds: int) -> None:
        super().__init__()
        self.api_metadata_scheduledevents: str = api_metadata_scheduledevents
        self.socket_timeout: int = socket_timeout_seconds
        self.delay_before_program_close_seconds: int = delay_before_program_close_seconds

    def query_for_events(self) -> ScheduledEvents:
        request = urllib.request.Request(self.api_metadata_scheduledevents)
        request.add_header("Metadata", "true")
        with urllib.request.urlopen(request, timeout=self.socket_timeout) as response:
            metadata_scheduledevents = json.loads(response.read())
            return ScheduledEvents(metadata_scheduledevents)

    def start_an_event(self, event: ScheduledEvent) -> Any:
        print_(f"Starting a scheduled event {event.eventid}.", eventid=event.eventid)
        # A node redeploy can follow immediately, sleep as at the end of the program
        time.sleep(self.delay_before_program_close_seconds)
        data = {"StartRequests": [{"EventId": event.eventid}]}
        data_bytes = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(self.api_metadata_scheduledevents, data=data_bytes)
        request.add_header("Metadata", "true")
        with urllib.request.urlopen(request, timeout=self.socket_timeout) as response:
            return response.read()


# Subprocess related tools, external dependencies somehow have to be running.
class SubprocessUtils(object):

    def __init__(self):
        raise AssertionError

    @staticmethod
    def subprocess_run(cmd: List[str], event: ScheduledEvent) -> None:
        print_(f"Running a command {cmd} for event {event.eventid}.", eventid=event.eventid)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        proc_output_reader = threading.Thread(target=SubprocessUtils._subprocess_stdout_reader,
                                              args=(cmd, event, proc))
        proc_output_reader.start()
        proc.wait()

    @staticmethod
    def _subprocess_stdout_reader(cmd: List[str], event: ScheduledEvent, proc: subprocess.Popen) -> None:
        subprocess_id = " ".join(cmd)
        for message in proc.stdout:
            print_(message, eventid=event.eventid, subprocess=subprocess_id)


# Tool to perform operations with the "kubectl" tool.
class KubectlManager(object):

    def __init__(self,
                 cache_dir: str,
                 kubectl_drain_options: List[str],
                 this_hostnames: ThisHostnames) -> None:
        super().__init__()
        self.kubectl_cordon_cache: CacheableList[ScheduledEvent] = CacheableList(cache_dir, "kubectl_cordon_cache")
        self.kubectl_drain_options: List[str] = kubectl_drain_options
        self.this_hostnames: ThisHostnames = this_hostnames

    def kubectl_cordon(self, event: ScheduledEvent) -> None:
        SubprocessUtils.subprocess_run(["kubectl", "cordon", self.this_hostnames.node_name], event)
        # Cache a simplified event. We don't need all the details there.
        self.kubectl_cordon_cache.append(ScheduledEvent({"EventId": event.eventid}))

    def kubectl_drain(self, event: ScheduledEvent) -> None:
        SubprocessUtils.subprocess_run(
            ["kubectl", "drain", self.this_hostnames.node_name] + self.kubectl_drain_options, event)

    def kubectl_uncordon(self, event: ScheduledEvent) -> None:
        SubprocessUtils.subprocess_run(["kubectl", "uncordon", self.this_hostnames.node_name], event)
        self.kubectl_cordon_cache.remove(event)


# The operator is here. Everything else is unnecessary.
class Seoperator2(object):

    def __init__(self,
                 cache_dir: str,
                 ignored_event_types: List[str],
                 this_hostnames: ThisHostnames,
                 scheduled_events_manager: ScheduledEventsManager,
                 kubectl_manager: KubectlManager) -> None:
        super().__init__()
        self.ignored_event_types = ignored_event_types
        self.this_hostnames: ThisHostnames = this_hostnames
        self.scheduled_events_manager: ScheduledEventsManager = scheduled_events_manager
        self.kubectl_manager: KubectlManager = kubectl_manager
        self.already_processed_events: CacheableList[str] = CacheableList(cache_dir, "already_processed_events")

    def handle_scheduled_events(self, events: ScheduledEvents) -> None:
        # If an event is finished, it will no longer be reported by the scheduledevents API.
        # uncordon nodes affected by scheduled events in the past.
        for cached_event in self.kubectl_manager.kubectl_cordon_cache:
            if not any(cached_event.eventid == event.eventid for event in events):
                print_(f"Found an event from the past {cached_event.eventid}.", eventid=cached_event.eventid)
                print_(f"Handling the past event {cached_event.eventid}.", eventid=cached_event.eventid)
                self.kubectl_manager.kubectl_uncordon(cached_event)
                print_(f"Handled the past event {cached_event.eventid}.", eventid=cached_event.eventid)

        if len(events) == 0:
            return

        print_(f"The current list of planned events includes {len(events)} events.", events=events)

        events = filter(lambda event: event.eventid not in self.already_processed_events, events)
        events = filter(lambda event: event.eventstatus == "Scheduled", events)
        events = filter(lambda event: self.this_hostnames.compute_name in event.resources, events)
        events = filter(lambda event: event.eventtype not in self.ignored_event_types, events)

        for event in events:
            print_(f"Found an event {event.eventid} ({event.eventtype}).", eventid=event.eventid)
            print_(f"Handling the event {event.eventid}.", eventid=event.eventtype)
            self.handle_scheduled_event(event)
            print_(f"Handled the event {event.eventid}.", eventid=event.eventid)
            self.already_processed_events.append(event.eventid)

    def handle_scheduled_event(self, event: ScheduledEvent) -> None:
        self.kubectl_manager.kubectl_cordon(event)
        self.kubectl_manager.kubectl_drain(event)
        self.scheduled_events_manager.start_an_event(event)


# Manager that takes care of graceful shutdown.
class LifeManager(object):

    def __init__(self, delay_before_program_close_seconds: int) -> None:
        super().__init__()
        self.delay_before_program_close_seconds: int = delay_before_program_close_seconds
        self.exit_threading_event: threading.Event = threading.Event()

        for some_signal in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
            signal.signal(some_signal,
                          lambda signal_number, current_stack_frame:
                          self.death_handler(signal_number))

    def death_handler(self, signal_number: Any):
        print_(f"Interrupted by signal {signal_number}, shutting down.")
        time.sleep(self.delay_before_program_close_seconds)
        self.exit_threading_event.set()


# Configuration - what can be set with parameters to the script.
class Config(JsonSerializable, object):

    def __init__(self, config_file: str, cache_dir: str) -> None:
        config_data = {}
        if os.path.isfile(config_file):
            with open(config_file) as f:
                config_data = json.load(f)

        self.config_file: str = config_file
        self.cache_dir: str = cache_dir

        self.api_metadata_instance: str = \
            config_data.get("api-metadata-instance",
                            "http://169.254.169.254/metadata/scheduledevents?api-version=2019-08-01")
        self.api_metadata_scheduledevents: str = \
            config_data.get("api-metadata-scheduledevents",
                            "http://169.254.169.254/metadata/instance?api-version=2020-09-01")

        self.main_loop_sleep_duration_seconds: int = config_data.get("main-loop-sleep-duration-seconds", 60)
        self.socket_timeout_seconds: int = config_data.get("socket-timeout-seconds", 10)
        self.ignored_event_types: List[str] = config_data.get("ignored-event-types", [])
        self.kubectl_drain_options: List[str] = config_data.get("kubectl-drain-options", [])
        self.delay_before_program_close_seconds: int = config_data.get("delay-before-program-close-seconds", 5)

    def __str__(self) -> str:
        return str(self.to_json())

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"{str(self.to_json())}")

    def to_json(self) -> Dict[str, Any]:
        return {
            "config_file": self.config_file,
            "cache_dir": self.cache_dir,
            "api_metadata_instance": self.api_metadata_instance,
            "api_metadata_scheduledevents": self.api_metadata_scheduledevents,
            "main_loop_sleep_duration_seconds": self.main_loop_sleep_duration_seconds,
            "socket_timeout_seconds": self.socket_timeout_seconds,
            "ignored_event_types": self.ignored_event_types,
            "kubectl_drain_options": self.kubectl_drain_options,
            "delay_before_program_close_seconds": self.delay_before_program_close_seconds,
        }


def main():
    try:
        print_("The operator started working.", sysversioninfo=sys.version_info)

        config_file_path = sys.argv[1] if len(sys.argv) > 1 else "/no/custom/config"
        cache_dir = sys.argv[2] if len(sys.argv) > 2 else "/do/not/store"

        # Disable automatic proxy server detection.
        # https://docs.microsoft.com/en-us/azure/virtual-machines/linux/instance-metadata-service?tabs=linux#proxies
        # https://docs.python.org/3.9/howto/urllib2.html#proxies
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        urllib.request.install_opener(opener)

        config = Config(config_file_path,
                        cache_dir)
        this_hostnames = ThisHostnames(config.api_metadata_instance,
                                       config.socket_timeout_seconds)
        scheduled_events_manager = ScheduledEventsManager(config.api_metadata_scheduledevents,
                                                          config.socket_timeout_seconds,
                                                          config.delay_before_program_close_seconds)
        kubectl_manager = KubectlManager(config.cache_dir,
                                         config.kubectl_drain_options,
                                         this_hostnames)
        life_manager = LifeManager(config.delay_before_program_close_seconds)
        operator = Seoperator2(config.cache_dir,
                               config.ignored_event_types,
                               this_hostnames,
                               scheduled_events_manager,
                               kubectl_manager)

        print_(f"The operator has been initialized.",
               config=config,
               this_hostnames=this_hostnames,
               already_processed_events=operator.already_processed_events,
               kubectl_cordon_cache=kubectl_manager.kubectl_cordon_cache,
               exit_threading_event_is_set=life_manager.exit_threading_event.is_set())

        while True:
            # print_("The operator is still working.")
            data = scheduled_events_manager.query_for_events()
            operator.handle_scheduled_events(data)
            if life_manager.exit_threading_event.wait(config.main_loop_sleep_duration_seconds):
                break

    except BaseException as e:
        traceback_formatted = str(traceback.format_exc())
        print_(f"There was a fatal error in my main loop, {e.__class__.__name__}.", traceback=traceback_formatted)
        sys.exit(1)


if __name__ == "__main__":
    main()
