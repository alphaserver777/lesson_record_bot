"""Entrypoint for Mini App backend API."""
import os

import uvicorn


if __name__ == "__main__":
    host = os.getenv("WEBAPI_HOST", "0.0.0.0")
    port = int(os.getenv("WEBAPI_PORT", "8000"))
    uvicorn.run("webapi.main:app", host=host, port=port, reload=False)
