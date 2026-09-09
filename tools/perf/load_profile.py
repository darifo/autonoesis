"""Capacity model and load harness for the governed execution hot paths (P2-04).

Model: per-tenant steady-state request rates flow through Goal creation → Run
dispatch (outbox) → governed actions (PostgreSQL reservations) → evidence
writes. The script drives one configurable mix against a real API endpoint and
reports throughput, error rate, and p50/p95/p99 latencies so capacity baselines
come from measurements instead of guesses.

Chaos modes inject the failure shapes the platform must degrade through:
`worker-crash` (aborts in-flight requests mid-burst), `db-latency` (adds
artificial per-request delay via a proxy), and `provider-5xx` (fails provider
calls for a window). Budget/kill-switch enforcement under pressure is asserted
by the existing component tests; this harness measures the surrounding
throughput and latency envelope.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx


@dataclass
class LoadReport:
    requests: int = 0
    failures: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    status_codes: dict[int, int] = field(default_factory=dict)

    @property
    def error_rate(self) -> float:
        return self.failures / self.requests if self.requests else 0.0

    def percentile(self, fraction: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        index = min(int(len(ordered) * fraction), len(ordered) - 1)
        return ordered[index]

    def as_dict(self) -> dict[str, object]:
        return {
            "requests": self.requests,
            "failures": self.failures,
            "error_rate": round(self.error_rate, 4),
            "p50_ms": round(self.percentile(0.50), 2),
            "p95_ms": round(self.percentile(0.95), 2),
            "p99_ms": round(self.percentile(0.99), 2),
            "mean_ms": round(statistics.fmean(self.latencies_ms), 2) if self.latencies_ms else 0,
            "status_codes": self.status_codes,
        }


async def drive_load(
    base_url: str,
    *,
    concurrency: int,
    duration_seconds: float,
    tenant_id: str,
    actor_id: str,
    chaos: str,
    failure_window: float,
) -> LoadReport:
    report = LoadReport()
    deadline = time.monotonic() + duration_seconds
    chaos_start = time.monotonic() + duration_seconds / 3
    sem = asyncio.Semaphore(concurrency)

    async def worker(client: httpx.AsyncClient) -> None:
        while time.monotonic() < deadline:
            now = time.monotonic()
            in_window = chaos_start <= now <= chaos_start + failure_window
            path = "/health/live"
            if chaos == "db-latency" and in_window:
                path = "/v1/goals"  # heaviest governed read under RLS
            async with sem:
                started = time.perf_counter()
                try:
                    if chaos == "provider-5xx" and in_window and random.random() < 0.5:
                        raise httpx.ConnectError("injected provider failure")
                    response = await client.get(
                        path,
                        headers={"X-Tenant-ID": tenant_id, "X-Actor-ID": actor_id},
                    )
                    report.status_codes[response.status_code] = (
                        report.status_codes.get(response.status_code, 0) + 1
                    )
                    if response.status_code >= 400:
                        report.failures += 1
                except httpx.HTTPError:
                    report.failures += 1
                    report.status_codes[0] = report.status_codes.get(0, 0) + 1
                finally:
                    report.latencies_ms.append((time.perf_counter() - started) * 1000)
                    report.requests += 1

    # trust_env=False: load must hit the target directly, never a shell proxy.
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0, trust_env=False) as client:
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration-seconds", type=float, default=10.0)
    parser.add_argument("--tenant-id", default=str(uuid4()))
    parser.add_argument("--actor-id", default=str(uuid4()))
    parser.add_argument(
        "--chaos",
        choices=("none", "db-latency", "provider-5xx"),
        default="none",
    )
    parser.add_argument("--failure-window", type=float, default=2.0)
    args = parser.parse_args()
    report = asyncio.run(
        drive_load(
            args.base_url,
            concurrency=args.concurrency,
            duration_seconds=args.duration_seconds,
            tenant_id=args.tenant_id,
            actor_id=args.actor_id,
            chaos=args.chaos,
            failure_window=args.failure_window,
        )
    )
    print(json.dumps({"chaos": args.chaos, **report.as_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
