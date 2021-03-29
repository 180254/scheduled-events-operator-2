#!/usr/bin/python3
import datetime
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import traceback
import typing
import urllib.error
import urllib.parse
import urllib.request

config_file = "/config/config.json"
metadata_scheduledevents_url = "http://169.254.169.254/metadata/scheduledevents?api-version=2019-08-01"
metadata_instance_url = "http://169.254.169.254/metadata/instance?api-version=2020-09-01"


class Context(object):
    def __init__(self):
        self.exit_event = threading.Event()
        self.processed_events = []
        self.this_hostnames = get_this_hostnames()

        config_data = read_config_file()
        self.ignore_events_of_types = config_data["ignoreEventsOfTypes"]
        self.loop_sleep_seconds = config_data["loopSleepSeconds"]
        self.uncordon_delay_seconds = config_data["uncordonDelaySeconds"]

    def serialize(self):
        return {
            "processed_events": self.processed_events,
            "this_hostnames": self.this_hostnames,
            "ignore_events_of_types": self.ignore_events_of_types,
            "loop_sleep_seconds": self.loop_sleep_seconds,
            "uncordon_delay_seconds": self.uncordon_delay_seconds,
        }


def read_config_file():
    config_data: typing.Dict[str, typing.Any] = {}
    if os.path.isfile(config_file):
        with open(config_file) as f:
            config_data = json.load(f)
    config_data.setdefault("ignoreEventsOfTypes", [])
    config_data.setdefault("loopSleepSeconds", 60)
    config_data.setdefault("uncordonDelaySeconds", 120)
    config_data["ignoreEventsOfTypes"] = list(map(str.lower, config_data["ignoreEventsOfTypes"]))
    return config_data


def print_(message, **kwargs):
    timestamp = datetime.datetime.utcnow().astimezone().replace(microsecond=0).isoformat()
    print(json.dumps({"timestamp": timestamp, "message": message, **kwargs}))


def subprocess_run(cmd, eventid):
    print_(f"Running a command: {cmd} for {eventid}.", eventid=eventid)
    timestamp = datetime.datetime.utcnow().astimezone().replace(microsecond=0).isoformat()
    json_formatter = \
        f" 2>&1 " \
        f"| jq -cRM " \
        f"--arg timestamp '{timestamp}' --arg eventid '{eventid}' " \
        f"'{{timestamp: $timestamp, message: ., eventid: $eventid}}'"
    subprocess.run([cmd + json_formatter], stdin=None, stdout=None, stderr=None, shell=True)


def b36_encode(num):
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while not result or num > 0:
        num, i = divmod(num, 36)
        result = digits[i] + result
    return result


# example
#   input: aks-default-36328368-vmss_18
#   output: aks-default-36328368-vmss00000i
def compute_name_to_node_name(compute_name):
    name_prefix, vm_index_base10 = compute_name.split("_")
    vm_index_base36 = b36_encode(int(vm_index_base10))
    return name_prefix + vm_index_base36.rjust(6, '0')


def get_this_hostnames():
    request = urllib.request.Request(metadata_instance_url)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=10) as response:
        metadata_instance = json.loads(response.read())
        compute_name = metadata_instance.get("compute").get("name")
        return {
            "hostname": socket.gethostname(),
            "computename": compute_name,
            "nodename": compute_name_to_node_name(compute_name),
        }


def get_scheduled_events():
    request = urllib.request.Request(metadata_scheduledevents_url)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=10) as response:
        metadata_scheduledevents = json.loads(response.read())
        return metadata_scheduledevents


def start_scheduled_event(context, eventid):
    print_(f"Starting scheduled event.", eventid=eventid)
    if context.exit_event.wait(30):  # give some time to external monitoring to collect logs
        return
    data = {"StartRequests": [{"EventId": eventid}]}
    databytes = json.dumps(data).encode('utf-8')
    request = urllib.request.Request(metadata_scheduledevents_url, data=databytes)
    request.add_header("Metadata", "true")
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def handle_scheduled_events(context, scheduled_events):
    events = scheduled_events["Events"]

    if len(events) > 0:
        print_(f"A new list of planned events.", events=events)

    for event in events:
        eventid = event['EventId']
        eventstatus = event['EventStatus']
        resources = event['Resources']
        eventtype = event['EventType']
        resourcetype = event['ResourceType']
        notbefore = event['NotBefore']

        if eventid not in context.processed_events:
            print_(f"A new event was found {eventid} ({eventtype}).", eventid=eventid)

            if eventstatus == "Scheduled" \
                    and any(hostname in resources for hostname in context.this_hostnames.values()) \
                    and eventtype.lower() not in context.ignore_events_of_types:
                print_(f"Handling the event {eventid}.", eventid=eventid)
                handle_scheduled_event(context, eventid)
                print_(f"Handled the event {eventid}.", eventid=eventid)

            else:
                print_(f"Skipping the event {eventid}.", eventid=eventid)

            context.processed_events.append(eventid)


def handle_scheduled_event(context, eventid):
    nodename = context.this_hostnames["nodename"]
    subprocess_run(f"kubectl cordon {nodename}", eventid)
    subprocess_run(f"kubectl drain {nodename} --delete-emptydir-data --ignore-daemonsets", eventid)

    # Perhaps this script will be killed before it can be executed.
    # However, nothing happened, the node remains 'unschedulable' and will soon be removed by the cluster autoscaler.
    uncordon_timer = threading.Timer(context.uncordon_delay_seconds,
                                     lambda: subprocess_run(f"kubectl uncordon {nodename}", eventid))
    uncordon_timer.start()

    start_scheduled_event(context, eventid)


def the_end(context, signal_number, current_stack_frame):
    print_(f"Interrupted by signal {signal_number}, shutting down.")
    context.exit_event.set()


def main():
    try:
        for some_signal in [signal.SIGTERM, signal.SIGINT, signal.SIGHUP]:
            signal.signal(some_signal,
                          lambda signal_number, current_stack_frame:
                          the_end(context, signal_number, current_stack_frame))

        print_("The operator started to work.")

        context = Context()
        print_(f"The configuration is loaded.", context=context.serialize())

        while True:
            print_("Another iteration of the operator's main loop has begun, i.e. the program is still running.")
            data = get_scheduled_events()
            handle_scheduled_events(context, data)
            if context.exit_event.wait(context.loop_sleep_seconds):
                break

    except Exception:
        traceback_formatted = str(traceback.format_exc())
        print_("Fatal error in the main loop.", traceback=traceback_formatted)
        sys.exit(1)


if __name__ == "__main__":
    main()
