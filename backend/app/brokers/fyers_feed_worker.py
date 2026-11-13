"""FYERS live-feed adapter running *only* in its own Python virtualenv.

Protocol: one JSON configuration line over stdin; one JSON event per stdout
line. Never print tokens, secrets, or raw broker exception bodies. This worker
has no access to the main API's session manager or execution endpoints.
"""
from __future__ import annotations

import json
import sys
import threading

_OUTPUT_LOCK = threading.Lock()


def _send(event, data=None):
    payload = {"type": event}
    if data is not None:
        payload["data"] = data
    with _OUTPUT_LOCK:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def main():
    try:
        config = json.loads(sys.stdin.readline())
        token = config["access_token"]
        symbols = config["symbols"]
        if not isinstance(token, str) or not token or not isinstance(symbols, list) or not symbols:
            raise ValueError("Missing token or subscription symbols")
        if not all(isinstance(s, str) and s for s in symbols):
            raise ValueError("Invalid subscription symbols")
        from fyers_apiv3.FyersWebsocket import data_ws
    except Exception:
        _send("error")
        return 1

    stop = threading.Event()
    socket = None

    def on_open():
        try:
            socket.subscribe(symbols=symbols, data_type="SymbolUpdate")
            socket.keep_running()
            _send("ready")
        except Exception:
            _send("error")
            stop.set()

    def on_message(message):
        if isinstance(message, dict):
            # Only market-data fields are forwarded, never credentials.
            allowed = (
                "symbol", "ltp", "last_traded_time", "bid_price1",
                "ask_price1", "vol_traded_today", "oi", "prev_close_price",
            )
            data = {k: message[k] for k in allowed if k in message}
            if data.get("symbol") in symbols and "ltp" in data:
                _send("tick", data)

    def on_error(*_args):
        # Do not leak raw SDK errors: they can contain auth headers or URLs.
        _send("error")
        stop.set()

    def on_close(*_args):
        stop.set()

    try:
        socket = data_ws.FyersDataSocket(
            access_token=token,
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        thread = threading.Thread(target=socket.connect, daemon=True)
        thread.start()
        stop.wait()
        return 0
    except Exception:
        _send("error")
        return 1
    finally:
        if socket is not None:
            try:
                socket.close_connection()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
