# services/tasks.py
import threading, time, json

# Global state (thread-safe enough for small Flask apps)
task_state = {
    "events": []  # list of {name, status, timestamp}
}

def add_task_event(name, status):
    """
    Add a new task event and keep only last N (e.g. 50).
    status can be "start", "complete", "error".
    """
    evt = {"name": name, "status": status, "ts": time.strftime("%H:%M:%S")}
    task_state["events"].insert(0, evt)
    task_state["events"] = task_state["events"][:50]
