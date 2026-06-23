"""
Resolve due open tips and print the updated reliability report.

Run this on a schedule (e.g. daily after the cash close) so the track record accrues:
    python resolve.py
Read-only — only fetches realized closes to score past tips.
"""
from __future__ import annotations

import tracker
from upstox_client import UpstoxClient

if __name__ == "__main__":
    client = UpstoxClient()
    tracker.resolve_open(client)
    tracker.print_report(tracker.report())
