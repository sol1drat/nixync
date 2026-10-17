import requests

HOST = "localhost"  # Replace with the managed host's IP
URL = f"http://{HOST}:8000/status"


def get_status():
    response = requests.get(URL, timeout=3)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    try:
        print(get_status())
    except requests.RequestException as e:
        print(f"Could not connect to host: {e}")
