import time

import requests

from fractale.ui.base import UserInterface


class WebAdapter(UserInterface):
    def __init__(self, api_url):
        self.api_url = api_url  # e.g. http://localhost:3000/api/events

    def _post(self, event_type, payload):
        requests.post(self.api_url, json={"type": event_type, "data": payload})

    def on_step_start(self, name, description, inputs):
        self._post("step_start", {"name": name, "desc": description})

    def on_log(self, message, level="info"):
        self._post("log", {"msg": message})

    def ask_user(self, question, options=None) -> str:
        # 1. Post the question to the UI
        req_id = f"req_{time.time()}"
        self._post("ask_user", {"question": question, "id": req_id})

        # 2. POLL for an answer (or use a Redis queue / Websocket listener)
        # This blocks the Manager thread until the frontend user clicks a button.
        while True:
            resp = requests.get(f"{self.api_url}/answers/{req_id}")
            if resp.status_code == 200:
                return resp.json()["answer"]
            time.sleep(1)
