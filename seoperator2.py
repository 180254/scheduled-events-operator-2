#!/usr/bin/python3 -u
import abc
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
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any, TypeVar, Generic, List, Iterator, Iterable, Dict, Optional

T = TypeVar("T")


# Serialize arbitrary Python objects to JSON.
# Fixes: TypeError: Object of type Xyz is not JSON serializable
# Fix consists of JsonSerializable, JsonSerializableEncoder.
class JsonSerializable(abc.ABC):

    @abc.abstractmethod
    def to_json(self) -> Any:
        pass

    def __str__(self) -> str:
        return str(self.to_json())

    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"{repr(self.to_json())})")


# Take a look at the documentation of JsonSerializable.
# https://docs.python.org/3/library/json.html#json.JSONEncoder.default
class JsonSerializableEncoder(json.JSONEncoder):

    def default(self, o: Any):
        if isinstance(o, JsonSerializable):
            return o.to_json()
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, o)


# Print in a version that produces output containing json.
def print_(message: str, **kwargs) -> None:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    print(json.dumps({"timestamp": timestamp, "message": message, **kwargs}, cls=JsonSerializableEncoder), flush=True)


# An interface that provides methods to "cache" (save) state.
# The state is stored on disk, under the specified key.
class Cacheable(Generic[T]):

    def __init__(self, cache_dir: str) -> None:
        super().__init__()
        self._cache_dir: str = cache_dir
        self._cache_enabled: bool = os.path.isdir(cache_dir)

    def _cache_read(self, key: str, default_value: T) -> T:
        if not self._cache_enabled:
            return default_value

        cache_file = os.path.join(self._cache_dir, key)
        try:
            with open(cache_file, "rb") as handle:
                return pickle.load(handle)
        except (OSError, IOError):
            return default_value

    def _cache_write(self, key: str, value: T) -> None:
        if not self._cache_enabled:
            pass

        cache_file = os.path.join(self._cache_dir, key)
        with open(cache_file, "wb") as handle:
            pickle.dump(value, handle)


# A list that saves the state to disk with each change.
# The list recreates its last state in the constructor, so it is immune to container restarts.
class CacheableList(Cacheable[List[T]], Iterable[T], JsonSerializable):

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

    def to_json(self) -> List[T]:
        return self._list


# This class has easily accessible information about the name of the VM on which this script is running.
# The "Azure Instance Metadata Service (Linux)" is helpful.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/instance-metadata-service?tabs=linux
class ThisHostnames(JsonSerializable):

    def __init__(self, api_metadata_instance: str, socket_timeout_seconds: int) -> None:
        super().__init__()
        request = urllib.request.Request(api_metadata_instance)
        request.add_header("Metadata", "true")
        with urllib.request.urlopen(request, timeout=socket_timeout_seconds) as response:
            if response.status // 100 != 2:
                raise ValueError("Instance metadata API responded with code {response.status}.")
            metadata_instance = json.loads(response.read())
            self.hostname: str = socket.gethostname()
            self.compute_name: str = metadata_instance["compute"]["name"]
            self.node_name: str = self._compute_name_to_node_name(self.compute_name)

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

    def to_json(self) -> Dict[str, Any]:
        return {
            "hostname": self.hostname,
            "compute_name": self.compute_name,
            "node_name": self.node_name,
        }


# An object-oriented representation of a single "scheduled event".
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
class ScheduledEvent(JsonSerializable):
    NOT_A_DATE = datetime.fromtimestamp(0, timezone.utc)
    NOT_A_DATE_ISO = datetime.fromtimestamp(0, timezone.utc).isoformat()

    def __init__(self, event: Dict[str, Any]) -> None:
        super().__init__()
        self._raw: Dict[str, Any] = event
        self.eventid: str = event["EventId"]
        self.eventtype: str = event["EventType"]
        self.resourcetype: str = event["ResourceType"]
        self.resources: List[str] = event["Resources"]
        self.eventstatus: str = event["EventStatus"]
        self.notbefore: datetime = self._parsedate_to_datetime(event["NotBefore"])
        self.description: str = event["Description"]
        self.eventsource: str = event["EventSource"]
        self.durationinseconds: int = event["DurationInSeconds"]
        self.seo2startedat: datetime = datetime.fromisoformat(event.get("Seo2StartedAt", ScheduledEvent.NOT_A_DATE_ISO))

    def mark_as_started(self) -> None:
        self.seo2startedat = datetime.now(timezone.utc)

    def seconds_since_started(self) -> float:
        return abs((datetime.now(timezone.utc) - self.seo2startedat).total_seconds())

    @staticmethod
    # https://bugs.python.org/issue30681
    def _parsedate_to_datetime(value) -> datetime:
        try:
            result = email.utils.parsedate_to_datetime(value)
            if result is None:
                raise ValueError
            return result
        except (TypeError, ValueError):
            return ScheduledEvent.NOT_A_DATE

    def to_json(self) -> Dict[str, Any]:
        return {
            **self._raw,
            "Seo2StartedAt": self.seo2startedat.isoformat()
        }


# An object-oriented representation of a whole "scheduled events" response.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
class ScheduledEvents(Iterable[ScheduledEvent], JsonSerializable):

    def __init__(self, events: Dict[str, Any]) -> None:
        super().__init__()
        self._raw: Dict[str, Any] = events
        self.document_incarnation: int = events["DocumentIncarnation"]
        self.events: List[ScheduledEvent] = list(map(ScheduledEvent, events.get("Events", [])))

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[ScheduledEvent]:
        return iter(self.events)

    def to_json(self) -> Dict[str, Any]:
        return self._raw


# A tool to perform operations on the "scheduled events" API.
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#query-for-events
# https://docs.microsoft.com/en-us/azure/virtual-machines/linux/scheduled-events#start-an-event
class ScheduledEventsManager:

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
            if response.status // 100 != 2:
                raise ValueError("ScheduledEvents API responded with code {response.status}.")
            metadata_scheduledevents = json.loads(response.read())
            return ScheduledEvents(metadata_scheduledevents)

    def start_an_event(self, event: ScheduledEvent) -> str:
        # A node redeploy can follow immediately, sleep as at the end of the program.
        # Give some time to external monitoring to collect logs.
        time.sleep(self.delay_before_program_close_seconds)
        data = {"StartRequests": [{"EventId": event.eventid}]}
        data_bytes = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(self.api_metadata_scheduledevents, data=data_bytes)
        request.add_header("Metadata", "true")
        with urllib.request.urlopen(request, timeout=self.socket_timeout) as response:
            if response.status // 100 != 2:
                raise ValueError("ScheduledEvents API responded with code {response.status}.")
            return response.read().decode('utf-8', 'ignore')


# Subprocess related tools, external dependencies somehow have to be running.
class SubprocessUtils:

    def __init__(self):
        raise AssertionError

    @staticmethod
    def subprocess_run_async(cmd: List[str], **_print_kwargs) -> 'subprocess.Popen[str]':
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        print_(f"Running a command {cmd}.", subprocess=proc.pid, **_print_kwargs)
        proc_output_reader = threading.Thread(target=SubprocessUtils._subprocess_stdout_reader,
                                              args=(proc,),
                                              kwargs=_print_kwargs)
        proc_output_reader.start()
        return proc

    @staticmethod
    # https://stackoverflow.com/a/18423003
    def _subprocess_stdout_reader(proc: 'subprocess.Popen[str]', **print_kwargs) -> None:
        if proc.stdout is not None:
            # pyre-ignore[16]: https://github.com/facebook/pyre-check/issues/221
            for message in proc.stdout:
                print_(message, subprocess=proc.pid, **print_kwargs)

    @staticmethod
    def subprocess_run_sync(cmd: List[str], **_print_kwargs) -> 'subprocess.CompletedProcess[str]':
        print_(f"Running a command {cmd}.", subprocess=-1, **_print_kwargs)
        return subprocess.run(cmd, text=True, capture_output=True, check=True)


# An object-oriented representation of a "kubectl version" response.
class KubectlVersion(JsonSerializable):

    def __init__(self, client_version: str, server_version: str, stderr: str) -> None:
        super().__init__()
        self.client_version: str = client_version
        self.server_version: str = server_version
        self.stderr: str = stderr

    def to_json(self) -> Dict[str, Any]:
        return {
            "client_version": self.client_version,
            "server_version": self.server_version,
            "stderr": self.stderr
        }


# Tool to perform operations with the "kubectl" tool.
class KubectlManager:

    def __init__(self,
                 cache_dir: str,
                 kubectl_drain_options: List[str],
                 this_hostnames: ThisHostnames) -> None:
        super().__init__()
        self.kubectl_cordon_cache: CacheableList[ScheduledEvent] = CacheableList(cache_dir, "kubectl_cordon_cache")
        self.kubectl_drain_options: List[str] = kubectl_drain_options
        self.this_hostnames: ThisHostnames = this_hostnames

    def kubectl_cordon(self, event: ScheduledEvent) -> None:
        proc = SubprocessUtils.subprocess_run_async(
            ["kubectl", "cordon", self.this_hostnames.node_name],
            eventid=event.eventid)
        exit_code = proc.wait()
        if exit_code != 0:
            raise ValueError("kubectl cordon operation failed with code {exit_code}.")
        self.kubectl_cordon_cache.append(event)

    def kubectl_drain(self, event: ScheduledEvent) -> None:
        proc = SubprocessUtils.subprocess_run_async(
            ["kubectl", "drain", self.this_hostnames.node_name, *self.kubectl_drain_options],
            eventid=event.eventid)
        exit_code = proc.wait()
        if exit_code != 0:
            raise ValueError("kubectl drain operation failed with code {exit_code}.")

    def kubectl_uncordon(self, event: ScheduledEvent) -> None:
        proc = SubprocessUtils.subprocess_run_async(
            ["kubectl", "uncordon", self.this_hostnames.node_name],
            eventid=event.eventid)
        exit_code = proc.wait()
        if exit_code != 0:
            raise ValueError("kubectl uncordon operation failed with code {exit_code}.")
        self.kubectl_cordon_cache.remove(event)

    @staticmethod
    def kubectl_version() -> KubectlVersion:
        kubectl_version_proc = SubprocessUtils.subprocess_run_sync(["kubectl", "version", "-o", "json"])
        try:
            versions = json.loads(kubectl_version_proc.stdout)
        except json.JSONDecodeError:
            print_("Failed to parse  'kubectl version' response.")
            versions = {}
        client_version = versions.get("clientVersion", {}).get("gitVersion", None)
        server_version = versions.get("serverVersion", {}).get("gitVersion", None)
        stderr = kubectl_version_proc.stderr.rstrip()
        return KubectlVersion(client_version, server_version, stderr)


# An object-oriented representation of a "processing-rules" config key element.
class ProcessingRule(JsonSerializable):

    def __init__(self, rule: Dict[str, Any]) -> None:
        super().__init__()
        self.rule_type: str = rule["rule-type"]
        self.event_type_is: List[str] = rule["event-type-is"]
        self.and_duration_in_seconds_less_equal_to: Optional[int] = rule.get("and-duration-in-seconds-less-equal-to")
        self.and_duration_in_seconds_greater_equal_to: Optional[int] = \
            rule.get("and-duration-in-seconds-greater-equal-to")
        self.and_compute_name_matches: Optional[str] = rule.get("and-compute-name-matches")
        self.and_compute_name_not_matches: Optional[str] = rule.get("and-compute-name-not-matches")
        self.and_node_name_matches: Optional[str] = rule.get("and-node-name-matches")
        self.and_node_name_not_matches: Optional[str] = rule.get("and-node-name-not-matches")

    def to_json(self) -> Dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "event_type_is": self.event_type_is,
            "and_duration_in_seconds_less_equal_to": self.and_duration_in_seconds_less_equal_to,
            "and_duration_in_seconds_greater_equal_to": self.and_duration_in_seconds_greater_equal_to,
            "and_compute_name_matches": self.and_compute_name_matches,
            "and_compute_name_not_matches": self.and_compute_name_not_matches,
            "and_node_name_matches": self.and_node_name_matches,
            "and_node_name_not_matches": self.and_node_name_not_matches,
        }


# A tool that looks at all the rules in List[ProcessingRule]
# and gives a final answer as to whether the event should be handled.
class ProcessingRuleProcessor:

    def __init__(self,
                 processing_rules: List[ProcessingRule],
                 this_hostnames: ThisHostnames) -> None:
        super().__init__()
        self.processing_rules: List[ProcessingRule] = processing_rules
        self.this_hostnames: ThisHostnames = this_hostnames

    def all_considered_should_handle(self, event: ScheduledEvent) -> bool:
        for processing_rule in self.processing_rules:
            if self._handle_event_if(processing_rule, event):
                return True
            if self._ignore_event_if(processing_rule, event):
                return False
        return True

    def _handle_event_if(self, processing_rule: ProcessingRule, event: ScheduledEvent) -> bool:
        return processing_rule.rule_type == "handle-event-if" and self._process_event_if(processing_rule, event)

    def _ignore_event_if(self, processing_rule: ProcessingRule, event: ScheduledEvent) -> bool:
        return processing_rule.rule_type == "ignore-event-if" and self._process_event_if(processing_rule, event)

    def _process_event_if(self, processing_rule: ProcessingRule, event: ScheduledEvent) -> bool:
        res = event.eventtype in processing_rule.event_type_is
        res &= (processing_rule.and_duration_in_seconds_less_equal_to is None
                or processing_rule.and_duration_in_seconds_less_equal_to >= event.durationinseconds > 0)
        res &= (processing_rule.and_duration_in_seconds_greater_equal_to is None
                or event.durationinseconds >= processing_rule.and_duration_in_seconds_greater_equal_to
                or event.durationinseconds < 0)
        res &= (processing_rule.and_compute_name_matches is None
                or fnmatch(self.this_hostnames.compute_name, processing_rule.and_compute_name_matches))
        res &= (processing_rule.and_compute_name_not_matches is None
                or not fnmatch(self.this_hostnames.compute_name, processing_rule.and_compute_name_not_matches))
        res &= (processing_rule.and_node_name_matches is None
                or fnmatch(self.this_hostnames.node_name, processing_rule.and_node_name_matches))
        res &= (processing_rule.and_node_name_not_matches is None
                or not fnmatch(self.this_hostnames.node_name, processing_rule.and_node_name_not_matches))
        return res


# Configuration - what can be set with parameters to the script.
class Config(JsonSerializable):

    def __init__(self, config_file: str, cache_dir: str) -> None:
        super().__init__()

        config_data = {}
        if os.path.isfile(config_file):
            with open(config_file, encoding='utf-8') as f:
                config_data = json.load(f)

        self.config_file: str = config_file
        self.cache_dir: str = cache_dir

        self.api_metadata_instance: str = \
            config_data.get("api-metadata-instance",
                            "http://169.254.169.254/metadata/scheduledevents?api-version=2020-07-01")
        self.api_metadata_scheduledevents: str = \
            config_data.get("api-metadata-scheduledevents",
                            "http://169.254.169.254/metadata/instance?api-version=2021-02-01")

        self.polling_frequency_seconds: int = config_data.get("polling-frequency-seconds", 60)
        self.socket_timeout_seconds: int = config_data.get("socket-timeout-seconds", 10)

        self.processing_rules: List[ProcessingRule] = \
            list(map(ProcessingRule, config_data.get("processing-rules", [])))

        self.kubectl_drain_options: List[str] = config_data.get("kubectl-drain-options", [])
        self.delay_before_uncordon_seconds: int = config_data.get("delay-before-uncordon-seconds", 120)
        self.delay_before_program_close_seconds: int = config_data.get("delay-before-program-close-seconds", 5)

    def to_json(self) -> Dict[str, Any]:
        return {
            "config_file": self.config_file,
            "cache_dir": self.cache_dir,
            "api_metadata_instance": self.api_metadata_instance,
            "api_metadata_scheduledevents": self.api_metadata_scheduledevents,
            "polling_frequency_seconds": self.polling_frequency_seconds,
            "socket_timeout_seconds": self.socket_timeout_seconds,
            "processing_rules": self.processing_rules,
            "kubectl_drain_options": self.kubectl_drain_options,
            "delay_before_program_close_seconds": self.delay_before_program_close_seconds,
        }


# The operator is here. Everything else is unnecessary.
class Seoperator2:

    def __init__(self,
                 cache_dir: str,
                 processing_rules_processor: ProcessingRuleProcessor,
                 this_hostnames: ThisHostnames,
                 scheduled_events_manager: ScheduledEventsManager,
                 kubectl_manager: KubectlManager,
                 delay_before_uncordon_seconds: int) -> None:
        super().__init__()
        self.processing_rules_processor: ProcessingRuleProcessor = processing_rules_processor
        self.this_hostnames: ThisHostnames = this_hostnames
        self.scheduled_events_manager: ScheduledEventsManager = scheduled_events_manager
        self.kubectl_manager: KubectlManager = kubectl_manager
        self.delay_before_uncordon_seconds: int = delay_before_uncordon_seconds
        self.already_processed_events: CacheableList[str] = CacheableList(cache_dir, "already_processed_events")

    def handle_scheduled_events(self, events: ScheduledEvents) -> None:
        # If an event is finished, it will no longer be reported by the scheduledevents API.
        # uncordon nodes affected by scheduled events in the past.
        for cached_event in self.kubectl_manager.kubectl_cordon_cache:
            if not any(cached_event.eventid == event.eventid for event in events) \
                    and cached_event.seconds_since_started() > self.delay_before_uncordon_seconds:
                print_(f"Found an event from the past {cached_event.eventid}.", eventid=cached_event.eventid)
                print_(f"Handling the past event {cached_event.eventid}.", eventid=cached_event.eventid)
                self.kubectl_manager.kubectl_uncordon(cached_event)
                print_(f"Handled the past event {cached_event.eventid}.", eventid=cached_event.eventid)

        if len(events) == 0:
            return

        print_(f"The current list of planned events includes {len(events)} events.", events=events)

        events2: Iterator[ScheduledEvent] = iter(events)
        events2 = filter(lambda event: event.eventid not in self.already_processed_events, events2)
        events2 = filter(lambda event: self.this_hostnames.compute_name in event.resources, events2)
        events2 = filter(lambda event: event.resourcetype == "VirtualMachine", events2)
        events2 = filter(lambda event: event.eventstatus == "Scheduled", events2)
        events2 = filter(self.processing_rules_processor.all_considered_should_handle, events2)

        for event in events2:
            print_(f"Found an event {event.eventid} ({event.eventtype}).", eventid=event.eventid)
            print_(f"Handling the event {event.eventid}.", eventid=event.eventtype)
            self.handle_scheduled_event(event)
            print_(f"Handled the event {event.eventid}.", eventid=event.eventid)
            self.already_processed_events.append(event.eventid)

    def handle_scheduled_event(self, event: ScheduledEvent) -> None:
        self.kubectl_manager.kubectl_cordon(event)
        self.kubectl_manager.kubectl_drain(event)

        if len(event.resources) > 1:
            # The event confirmation applies to all resources in the event,
            # it is not possible to start the event for one machine.
            # As we do not want to start the event prematurely, we are not starting the event at all.

            # We could also choose the leader and (on that node) do handling for each resource separately,
            # but then we will increase the processing time and/or memory usage (both of them are in short supply).

            # Azure will start the event when the time to handle it has passed.
            # Azure will then delete the node when it notices that it is not being used.
            print_(f"Not starting the scheduled event {event.eventid},"
                   f"the event affects multiple nodes.", eventid=event.eventid)
            self.kubectl_manager.kubectl_cordon_cache.remove(event)
        else:
            print_(f"Starting the scheduled event {event.eventid}.", eventid=event.eventid)
            response = self.scheduled_events_manager.start_an_event(event)
            print_(f"Started the scheduled event {event.eventid}, response='{response}'.", eventid=event.eventid)


# Manager that takes care of graceful shutdown.
class LifeManager:

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
        # Give some time to external monitoring to collect logs.
        time.sleep(self.delay_before_program_close_seconds)
        self.exit_threading_event.set()


def main():
    try:
        print_("The operator started working.")

        config_file_path = sys.argv[1] if len(sys.argv) > 1 else "/no/custom/config"
        cache_dir = sys.argv[2] if len(sys.argv) > 2 else "/do/not/store"

        # Disable automatic proxy server detection.
        # https://docs.microsoft.com/en-us/azure/virtual-machines/linux/instance-metadata-service?tabs=linux#proxies
        # https://docs.python.org/3.9/howto/urllib2.html#proxies
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        urllib.request.install_opener(opener)

        # Initializing helper classes.
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
        processing_rules_processor = ProcessingRuleProcessor(config.processing_rules,
                                                             this_hostnames)
        life_manager = LifeManager(config.delay_before_program_close_seconds)
        operator = Seoperator2(config.cache_dir,
                               processing_rules_processor,
                               this_hostnames,
                               scheduled_events_manager,
                               kubectl_manager,
                               config.delay_before_uncordon_seconds)

        # Checking the environment.
        app_version = datetime.fromtimestamp(os.path.getmtime(__file__)).astimezone().isoformat()
        sys_version = sys.version_info
        kubectl_version = KubectlManager.kubectl_version()

        print_("The operator has been initialized.",
               app_version=app_version,
               sys_version=sys_version,
               kubectl_version=kubectl_version,
               config=config,
               this_hostnames=this_hostnames,
               already_processed_events=operator.already_processed_events,
               kubectl_cordon_cache=kubectl_manager.kubectl_cordon_cache,
               exit_threading_event_is_set=life_manager.exit_threading_event.is_set())

        while True:
            # print_("The operator is still working.")
            data = scheduled_events_manager.query_for_events()
            operator.handle_scheduled_events(data)
            if life_manager.exit_threading_event.wait(config.polling_frequency_seconds):
                break

    except BaseException as e:
        traceback_formatted = str(traceback.format_exc())
        print_(f"There was a fatal error in my main loop, {e.__class__.__name__}.", traceback=traceback_formatted)
        sys.exit(1)


if __name__ == "__main__":
    main()
