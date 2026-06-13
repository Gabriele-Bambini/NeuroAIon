"""Shared HTTP helpers for source clients."""
from __future__ import annotations

import time
from typing import Any

import requests

from .. import config

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})


def http_get(url: str, params: dict[str, Any] | None = None, *, timeout: int = 30,
             accept: str = "application/json") -> requests.Response:
    """GET with a polite User-Agent and one gentle retry on transient failure."""
    headers = {"Accept": accept}
    for attempt in range(2):
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException:
            if attempt == 1:
                raise
            time.sleep(1.5)
    raise RuntimeError("unreachable")


def clean(text: str | None) -> str:
    return (text or "").strip().replace("\n", " ")
