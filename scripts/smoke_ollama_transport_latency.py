"""Measure a bounded Ollama HTTP stream without printing prompts or model text.

This is an independent diagnostic client. It deliberately does not replace
Aurora's urllib transport and opens one new direct connection per run.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import getproxies


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.ollama_request_policy import normalize_keep_alive, thinking_payload_value
from modules.settings import settings


DEFAULT_PROMPT = "只回复：测试成功。"
DEFAULT_RUNS = 5
MAX_RUNS = 20
PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=str(settings.get("ollama.host", "http://127.0.0.1:11434")).strip(),
        help="Ollama base URL.",
    )
    parser.add_argument(
        "--model",
        default=str(
            settings.get("resolved_chat_model", "")
            or settings.get("chat_model", "")
            or ""
        ).strip(),
        help="Installed Ollama chat model.",
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--think", choices=("default", "on", "off"), default="off")
    parser.add_argument(
        "--keep-alive",
        default="30m",
        help='Ollama duration, or "default" to omit the field.',
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--stall-threshold-ms", type=float, default=2000.0)
    parser.add_argument("--skip-ollama-ps", action="store_true")
    return parser.parse_args(argv)


def validate_args(args):
    if not args.host:
        raise ValueError("--host must not be empty")
    if not args.model:
        raise ValueError("No Ollama model selected; pass --model MODEL.")
    if not 1 <= args.runs <= MAX_RUNS:
        raise ValueError(f"--runs must be between 1 and {MAX_RUNS}")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than zero")
    if args.stall_threshold_ms < 0:
        raise ValueError("--stall-threshold-ms must not be negative")
    normalize_keep_alive(args.keep_alive)


def build_payload(model, prompt, think_mode, keep_alive):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
    }
    think_value = thinking_payload_value(think_mode)
    if think_value is not None:
        payload["think"] = think_value
    duration = normalize_keep_alive(keep_alive)
    if duration is not None:
        payload["keep_alive"] = duration
    return payload


def _elapsed_ms(start, end):
    if start is None or end is None:
        return None
    return max(0.0, (end - start) * 1000.0)


def _sanitize_proxy(value):
    if not value:
        return None
    parsed = urlsplit(value if "://" in value else f"//{value}")
    if parsed.hostname:
        try:
            port = parsed.port
        except ValueError:
            port = None
        return {
            "configured": True,
            "scheme": parsed.scheme or None,
            "host": parsed.hostname,
            "port": port,
            "credentials_present": parsed.username is not None or parsed.password is not None,
        }
    return {"configured": True, "value_redacted": True}


def proxy_environment_snapshot():
    snapshot = {}
    for name in PROXY_ENV_NAMES:
        value = os.environ.get(name)
        if name.casefold() == "no_proxy":
            snapshot[name] = (
                {"configured": True, "entry_count": len([item for item in value.split(",") if item.strip()])}
                if value
                else None
            )
        else:
            snapshot[name] = _sanitize_proxy(value)
    return snapshot


def urllib_proxy_snapshot():
    return {
        str(scheme): _sanitize_proxy(str(value))
        for scheme, value in getproxies().items()
    }


def ollama_ps_snapshot(label):
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return {
            "type": "ollama_ps",
            "label": label,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"type": "ollama_ps", "label": label, "error": str(error)}


def _connect_resolved(addresses, timeout):
    last_error = None
    for family, socktype, proto, _canonname, sockaddr in addresses:
        candidate = socket.socket(family, socktype, proto)
        candidate.settimeout(timeout)
        try:
            candidate.connect(sockaddr)
            return candidate
        except OSError as error:
            last_error = error
            candidate.close()
    if last_error is not None:
        raise last_error
    raise OSError("DNS returned no usable addresses")


def _open_connection(parsed, addresses, timeout):
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    connection_class = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_class(parsed.hostname, port=port, timeout=timeout)
    raw_socket = _connect_resolved(addresses, timeout)
    if parsed.scheme == "https":
        context = ssl.create_default_context()
        raw_socket = context.wrap_socket(raw_socket, server_hostname=parsed.hostname)
    connection.sock = raw_socket
    return connection


def _parse_ndjson_line(raw_line):
    if not raw_line.strip():
        return None
    value = json.loads(raw_line.decode("utf-8"))
    return value if isinstance(value, dict) else None


def _final_metrics(data):
    output = {}
    for name in ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration"):
        value = data.get(name)
        output[f"{name}_ms"] = value / 1_000_000.0 if isinstance(value, int) else None
    for name in ("prompt_eval_count", "eval_count"):
        value = data.get(name)
        output[name] = value if isinstance(value, int) and not isinstance(value, bool) else None
    return output


def run_once(host, model, prompt, think_mode, keep_alive, timeout, run_index, stall_threshold_ms):
    parsed = urlsplit(host.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--host must be an http or https URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    endpoint = f"{parsed.path.rstrip('/')}/api/chat" or "/api/chat"
    payload = build_payload(model, prompt, think_mode, keep_alive)
    body = json.dumps(payload).encode("utf-8")
    report = {
        "type": "transport_run_summary",
        "run_index": run_index,
        "wall_start_utc": datetime.now(timezone.utc).isoformat(),
        "host": f"{parsed.scheme}://{parsed.hostname}:{port}",
        "model": model,
        "think_mode": think_mode,
        "think_payload_value": thinking_payload_value(think_mode),
        "keep_alive": normalize_keep_alive(keep_alive),
        "status": "failed",
        "http_status": None,
        "response_bytes": 0,
        "ndjson_line_count": 0,
        "reasoning_chars": 0,
        "visible_content_chars": 0,
        "error": "",
    }
    request_start = monotonic()
    connection = None
    response = None
    dns_start = None
    dns_end = None
    connect_start = None
    connect_end = None
    headers_start = None
    headers_end = None
    body_start = None
    body_end = None
    response_wait_start = None
    response_headers = None
    first_body_byte = None
    first_ndjson_line = None
    first_model_output = None
    first_content = None
    stream_end = None
    try:
        dns_start = monotonic()
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        dns_end = monotonic()

        connect_start = monotonic()
        connection = _open_connection(parsed, addresses, timeout)
        connect_end = monotonic()

        headers_start = monotonic()
        connection.putrequest("POST", endpoint, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", parsed.netloc)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("Connection", "close")
        connection.endheaders()
        headers_end = monotonic()

        body_start = monotonic()
        connection.send(body)
        body_end = monotonic()

        response_wait_start = monotonic()
        response = connection.getresponse()
        response_headers = monotonic()
        report["http_status"] = response.status

        first = response.read(1)
        if first:
            first_body_byte = monotonic()
            raw_line = first + response.readline()
        else:
            raw_line = b""

        final_data = None
        while raw_line:
            report["response_bytes"] += len(raw_line)
            if raw_line.strip():
                line_time = monotonic()
                if first_ndjson_line is None:
                    first_ndjson_line = line_time
                data = _parse_ndjson_line(raw_line)
                if data is not None:
                    report["ndjson_line_count"] += 1
                    message = data.get("message") or {}
                    thinking = message.get("thinking", data.get("thinking", ""))
                    reasoning = message.get("reasoning", data.get("reasoning", ""))
                    content = message.get("content", "")
                    reasoning_chars = sum(
                        len(value)
                        for value in (thinking, reasoning)
                        if isinstance(value, str)
                    )
                    if reasoning_chars or (isinstance(content, str) and content):
                        if first_model_output is None:
                            first_model_output = line_time
                    report["reasoning_chars"] += reasoning_chars
                    if isinstance(content, str) and content:
                        if first_content is None:
                            first_content = line_time
                        report["visible_content_chars"] += len(content)
                    if data.get("done"):
                        final_data = data
            raw_line = response.readline()
        stream_end = monotonic()
        if final_data is not None:
            report.update(_final_metrics(final_data))
        if response.status >= 400:
            report["error"] = f"Ollama returned HTTP {response.status}"
        elif final_data is None:
            report["error"] = "Ollama stream ended without a done message"
        else:
            report["status"] = "completed"

    except (OSError, http.client.HTTPException, ValueError, json.JSONDecodeError) as error:
        stream_end = monotonic()
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()

    report.update({
        "dns_ms": _elapsed_ms(dns_start, dns_end),
        "connect_ms": _elapsed_ms(connect_start, connect_end),
        "request_headers_send_ms": _elapsed_ms(headers_start, headers_end),
        "request_body_send_ms": _elapsed_ms(body_start, body_end),
        "wait_response_headers_ms": _elapsed_ms(response_wait_start, response_headers),
        "request_to_response_headers_ms": _elapsed_ms(request_start, response_headers),
        "response_headers_to_first_body_byte_ms": _elapsed_ms(response_headers, first_body_byte),
        "request_to_first_body_byte_ms": _elapsed_ms(request_start, first_body_byte),
        "request_to_first_ndjson_line_ms": _elapsed_ms(request_start, first_ndjson_line),
        "request_to_first_model_output_ms": _elapsed_ms(request_start, first_model_output),
        "request_to_first_content_ms": _elapsed_ms(request_start, first_content),
        "stream_total_ms": _elapsed_ms(request_start, stream_end),
    })

    latency = report.get("request_to_first_model_output_ms")
    report["stall_threshold_ms"] = stall_threshold_ms
    report["stall_detected"] = isinstance(latency, (int, float)) and latency > stall_threshold_ms
    return report


def main(argv=None):
    args = parse_args(argv)
    try:
        validate_args(args)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    print(json.dumps({
        "type": "diagnostic_environment",
        "transport": "direct_http_client_new_connection_per_run",
        "proxy_environment": proxy_environment_snapshot(),
        "urllib_detected_proxies": urllib_proxy_snapshot(),
    }, ensure_ascii=False, indent=2), flush=True)
    if not args.skip_ollama_ps:
        print(json.dumps(ollama_ps_snapshot("before"), ensure_ascii=False, indent=2), flush=True)

    reports = []
    for run_index in range(1, args.runs + 1):
        if not args.skip_ollama_ps:
            print(json.dumps(
                ollama_ps_snapshot(f"before_run_{run_index}"),
                ensure_ascii=False,
                indent=2,
            ), flush=True)
        report = run_once(
            args.host,
            args.model,
            args.prompt,
            args.think,
            args.keep_alive,
            args.timeout,
            run_index,
            args.stall_threshold_ms,
        )
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        if report["stall_detected"] and not args.skip_ollama_ps:
            print(json.dumps(
                ollama_ps_snapshot(f"stall_run_{run_index}"),
                ensure_ascii=False,
                indent=2,
            ), flush=True)

    if not args.skip_ollama_ps:
        print(json.dumps(ollama_ps_snapshot("after"), ensure_ascii=False, indent=2), flush=True)
    if any(report["status"] != "completed" for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
