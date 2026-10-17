import socket

from fastapi import FastAPI

app = FastAPI()


@app.get("/status")
def get_status():
    with open("/proc/uptime", encoding="utf-8") as f:
        uptime = int(float(f.read().split()[0]))

    return {
        "hostname": socket.gethostname(),
        "status": "online",
        "uptime_seconds": uptime,
    }
