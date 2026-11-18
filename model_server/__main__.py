"""Run the model server: ``python -m model_server`` (loopback, port 8100 by default; see config.py for the environment)."""
import os

import uvicorn

from .app import create_app
from .config import ServerConfig


def main() -> None:
    host = os.environ.get("EDEN_MODEL_HOST", "127.0.0.1")
    port = int(os.environ.get("EDEN_MODEL_PORT", "8100"))
    uvicorn.run(create_app(ServerConfig.from_env()), host=host, port=port, log_level=os.environ.get("EDEN_MODEL_LOG", "warning"))


if __name__ == "__main__":
    main()
