"""Shared HTTP client. Retries, sane timeouts, honest failures."""
from __future__ import annotations

import time
import httpx

UA = "eu-funds-radar/1.0 (personal funding monitor; contact via repo)"


def client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": UA, "Accept-Language": "en,bs;q=0.8,hr;q=0.8"},
    )


def retry(fn, attempts: int = 3, backoff: float = 2.0, label: str = ""):
    """Run fn(), retrying transient failures. Re-raises the last error."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - we genuinely want any failure
            last = e
            if i < attempts - 1:
                time.sleep(backoff * (2**i))
    raise RuntimeError(f"{label or 'request'} failed after {attempts} attempts: {last}")
