#!/usr/bin/env python3
"""
Refreshes data.json for the Shop > Pre-Delivery CS dashboard.

Pulls two things from Metabase (database_id = kapture/pop, see METABASE_DATABASE_ID):
  1. Daily ticket counts by Disposition Level 3, for Shop > Order Related - Pre Delivery,
     filtered to source = Chat and agent-disposed (excludes blank/POP/POPclub bot tickets).
  2. Daily order counts (count(distinct sub_order_number), status != 'Discard'), dated by
     date_created shifted to IST (+5:30).

It then aggregates both into the shapes the dashboard (index.html) expects:
  - daily / weekly ticket counts by Level 3
  - dailyDelivered14d / weeklyDelivered14d : trailing 14-day order-count denominators

Required environment variables:
  METABASE_URL          e.g. https://metabase.yourcompany.com
  METABASE_API_KEY      a Metabase API key (Admin > Settings > Authentication > API Keys)
  METABASE_DATABASE_ID  defaults to 16 if unset (matches the database used during dashboard build)

Optional:
  CUTOFF_DATE           YYYY-MM-DD, defaults to "yesterday in IST" (last fully-complete day)
  TICKET_LOOKBACK_DAYS  defaults to 120
  ORDER_LOOKBACK_DAYS   defaults to 140 (needs 14 extra days before the earliest ticket day,
                        for the trailing-14-day rolling calc)
"""
import os
import sys
import json
import datetime as dt
from collections import defaultdict

import requests

METABASE_URL = os.environ["METABASE_URL"].rstrip("/")
METABASE_API_KEY = os.environ["METABASE_API_KEY"]
METABASE_DATABASE_ID = int(os.environ.get("METABASE_DATABASE_ID", "16"))

TICKET_LOOKBACK_DAYS = int(os.environ.get("TICKET_LOOKBACK_DAYS", "120"))
ORDER_LOOKBACK_DAYS = int(os.environ.get("ORDER_LOOKBACK_DAYS", "140"))

CATS = [
    "Order Status",
    "Cancellation Request",
    "Order Cancelled - Refund Status",
    "Update Information",
]
COLORS = {
    "Order Status": "#2F3E63",
    "Cancellation Request": "#D9932E",
    "Order Cancelled - Refund Status": "#BE5A48",
    "Update Information": "#1F8A73",
}

session = requests.Session()
session.headers.update({"x-api-key": METABASE_API_KEY, "Content-Type": "application/json"})


def run_query(sql: str):
    """Runs a native SQL query against Metabase and returns rows as list-of-dicts."""
    resp = session.post(
        f"{METABASE_URL}/api/dataset",
        json={
            "database": METABASE_DATABASE_ID,
            "type": "native",
            "native": {"query": sql},
        },
        timeout=120,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") == "failed":
        raise RuntimeError(f"Metabase query failed: {payload.get('error')}")
    cols = [c["name"] for c in payload["data"]["cols"]]
    rows = payload["data"]["rows"]
    return [dict(zip(cols, row)) for row in rows]


def week_start(date_str: str) -> str:
    """Returns the Sunday (YYYY-MM-DD) of the week containing date_str."""
    d = dt.date.fromisoformat(date_str[:10])
    offset = (d.weekday() + 1) % 7  # Monday=0..Sunday=6 -> Sunday offset=0
    return (d - dt.timedelta(days=offset)).isoformat()


def daterange(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d +=
