import json
from queue import Queue

display_queue = Queue()

OUTPUT_MODE = "laptop"

def set_output_mode(mode):
    global OUTPUT_MODE
    OUTPUT_MODE = mode

def get_output_mode():
    return OUTPUT_MODE

def send_event(event_type, data=None):
    display_queue.put(json.dumps({"type": event_type, "data": data}))

def send_text(text):
    send_event("text", text)

def reset_display():
    send_event("reset")
