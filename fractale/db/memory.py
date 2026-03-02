import os
import time
from datetime import datetime
from typing import Any, Dict, List

from rich import print

import fractale.utils as utils


class MemoryBackend:
    """
    A simple chronological event logger.
    Re-assembling the graph is just a matter of reading the list in order.
    We can add more database options proper when needed.
    """

    def __init__(self):
        # A flat list of every event that happens in the process
        self.events: List[Dict[str, Any]] = []
        # Tokens, etc.
        self.metrics: List[Dict[str, Any]] = []

    def record(
        self, event_type: str, step_name: str, step_type: str, payload: Dict[str, Any] = None
    ):
        """
        The only function you really need.
        Appends a snapshot of the state machine's pulse.
        """
        entry = {
            "timestamp": time.time(),
            "event": event_type,  # 'enter', 'exit', 'transition'
            "step": step_name,
            "type": step_type,
            "data": payload or {},
        }
        self.events.append(entry)
        print(f"📝: {entry['timestamp']} | {event_type.upper()} | {step_name}")

    def record_metric(self, payload: Dict[str, Any] = None):
        """
        Record random metrics payload, larger data for separate save
        """
        entry = {"timestamp": time.time(), "data": payload or {}}
        self.metrics.append(entry)
        print(f"📝: {entry['timestamp']} | metric")

    # Helper methods to mirror your interface
    def start_step(self, name: str, step_type: str, data: dict):
        self.record("enter", name, step_type, data)

    def finish_step(self, name: str, step_type: str, data: dict):
        self.record("exit", name, step_type, data)

    def save(self, data=None):
        """
        Save results to json in PWD.
        """
        os.makedirs(".fractale", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(".fractale", f"{timestamp}-events.json")
        print(f"💾 Saving results to {path}")
        results = {"events": self.events}
        if data:
            results["machine"] = data
        utils.write_json(results, path)

        if not self.metrics:
            return
        path = os.path.join(".fractale", f"{timestamp}-metrics.json")
        utils.write_json(self.metrics, path)
