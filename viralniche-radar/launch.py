"""Start the local app and open its dashboard once the server is ready."""

import http.client
import json
import os
import threading
import time
import webbrowser
from pathlib import Path

URL = "http://127.0.0.1:8000"


def is_running() -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=1)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        data = json.loads(response.read())
        return response.status == 200 and data.get("status") == "ok" and "youtube_key_configured" in data
    except (OSError, http.client.HTTPException, ValueError, AttributeError):
        return False
    finally:
        connection.close()


def open_when_ready():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if is_running():
            webbrowser.open(URL)
            return
        time.sleep(.5)


def main():
    os.chdir(Path(__file__).resolve().parent)
    if is_running():
        webbrowser.open(URL)
        print(f"ViralNiche Radar is already running at {URL}")
        return
    import uvicorn

    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
