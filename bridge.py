import json
from queue import Queue


display_queue = Queue()


def send_event(event_type, data=None):
    display_queue.put(json.dumps({"type": event_type, "data": data}))


def send_text(text):
    send_event("text", text)


def reset_display():
    send_event("reset")


def show_route(route_payload):
    if isinstance(route_payload, str):
        route_payload = json.loads(route_payload)
    send_event("route", route_payload)
