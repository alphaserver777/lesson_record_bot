"""HTTP probes for the bot process."""
import asyncio
import json
import os


class HealthState:
    def __init__(self) -> None:
        self.ready = False


async def _write_json_response(writer: asyncio.StreamWriter, status_code: int, payload: dict[str, str]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    reason = "OK" if status_code == 200 else "Service Unavailable"
    writer.write(
        (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        + body
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def _handle_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: HealthState,
) -> None:
    request_line = await reader.readline()
    parts = request_line.decode("utf-8", errors="ignore").split()
    path = parts[1] if len(parts) >= 2 else "/"

    if path == "/health":
        await _write_json_response(writer, 200, {"status": "ok"})
        return

    if path == "/ready":
        if state.ready:
            await _write_json_response(writer, 200, {"status": "ready"})
        else:
            await _write_json_response(writer, 503, {"status": "not_ready"})
        return

    await _write_json_response(writer, 404, {"status": "not_found"})


async def start_health_server(state: HealthState) -> asyncio.AbstractServer:
    host = os.getenv("BOT_HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("BOT_HEALTH_PORT", "8081"))
    return await asyncio.start_server(lambda reader, writer: _handle_request(reader, writer, state), host, port)
