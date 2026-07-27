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
        d += dt.timedelta(days=1)


def main():
    now_ist = dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)
    cutoff_date = os.environ.get("CUTOFF_DATE") or (now_ist.date() - dt.timedelta(days=1)).isoformat()
    cutoff = dt.date.fromisoformat(cutoff_date)

    ticket_start = (cutoff - dt.timedelta(days=TICKET_LOOKBACK_DAYS - 1)).isoformat()
    order_start = (cutoff - dt.timedelta(days=ORDER_LOOKBACK_DAYS - 1)).isoformat()
    order_upper_bound = f"{cutoff.isoformat()} 18:30:00"  # midnight IST of cutoff+1, in UTC

    print(f"Cutoff date (IST): {cutoff_date}")
    print(f"Ticket lookback from: {ticket_start}")
    print(f"Order lookback from: {order_start}, upper bound (UTC): {order_upper_bound}")

    # 1. Ticket data: Shop > Order Related - Pre Delivery, Chat source, agent-disposed
    ticket_sql = f"""
    select createdate, get_json_object(dispositionfolderlevel,'$.Folder level 3') as l3, count(*) as cnt
    from kapture.raw_ticket_reports
    where get_json_object(dispositionfolderlevel,'$.Folder level 1') = 'Shop'
    and get_json_object(dispositionfolderlevel,'$.Folder level 2') = 'Order Related - Pre Delivery'
    and sourcetype = 'Chat'
    and disposeby is not null and disposeby <> '' and lower(disposeby) not in ('pop','popclub')
    and createdate >= '{ticket_start}' and createdate <= '{cutoff_date}'
    group by 1,2
    order by 1,2
    """
    ticket_rows = run_query(ticket_sql)

    daily = defaultdict(lambda: [0, 0, 0, 0])
    for row in ticket_rows:
        date_str = str(row["createdate"])[:10]
        l3 = row["l3"]
        cnt = row["cnt"]
        if l3 in CATS:
            daily[date_str][CATS.index(l3)] = cnt
    # ensure every day in the lookback window has an entry (even if all zero)
    for d in daterange(dt.date.fromisoformat(ticket_start), cutoff):
        daily.setdefault(d.isoformat(), [0, 0, 0, 0])
    daily = dict(sorted(daily.items()))

    # weekly ticket rollup (Sun-Sat)
    weekly = defaultdict(lambda: [0, 0, 0, 0])
    for date_str, counts in daily.items():
        wk = week_start(date_str)
        for i in range(4):
            weekly[wk][i] += counts[i]
    weekly = dict(sorted(weekly.items()))

    # 2. Order data: all statuses except Discard, distinct orders, date_created in IST
    order_sql = f"""
    select date(date_created + interval '5 hours 30 minutes') as order_date,
           count(distinct sub_order_number) as order_count
    from pop.app_order_line
    where status != 'Discard'
    and date_created >= '{order_start}'
    and date_created < '{order_upper_bound}'
    group by 1
    order by 1
    """
    order_rows = run_query(order_sql)
    order_daily = defaultdict(int)
    for row in order_rows:
        order_daily[str(row["order_date"])[:10]] = row["order_count"]
    for d in daterange(dt.date.fromisoformat(order_start), cutoff):
        order_daily.setdefault(d.isoformat(), 0)
    order_daily = dict(sorted(order_daily.items()))

    order_dates_sorted = list(order_daily.keys())

    # trailing 14-day rolling sum, daily
    dailyDelivered14d = {}
    window_sum = 0
    window = []
    for d in order_dates_sorted:
        window.append(order_daily[d])
        window_sum += order_daily[d]
        if len(window) > 14:
            window_sum -= window.pop(0)
        dailyDelivered14d[d] = window_sum
    # trim to the ticket display window only
    dailyDelivered14d = {d: v for d, v in dailyDelivered14d.items() if d >= ticket_start}

    # weekly order rollup + trailing 2-week (14-day) sum
    weekly_order = defaultdict(int)
    for d, cnt in order_daily.items():
        weekly_order[week_start(d)] += cnt
    weekly_order = dict(sorted(weekly_order.items()))
    week_keys_sorted = list(weekly_order.keys())
    weeklyDelivered14d = {}
    for i, wk in enumerate(week_keys_sorted):
        prior = weekly_order[week_keys_sorted[i - 1]] if i > 0 else 0
        weeklyDelivered14d[wk] = weekly_order[wk] + prior
    # trim to the ticket display window only
    min_ticket_week = week_start(ticket_start)
    weeklyDelivered14d = {wk: v for wk, v in weeklyDelivered14d.items() if wk >= min_ticket_week}

    data_max = max(daily.keys())
    data_min = min(weekly.keys())
    latest_week = max(weekly.keys())
    latest_week_end = (dt.date.fromisoformat(latest_week) + dt.timedelta(days=6)).isoformat()
    partial_week = latest_week if data_max < latest_week_end else ""

    out = {
        "CATS": CATS,
        "COLORS": COLORS,
        "daily": daily,
        "weekly": weekly,
        "dailyDelivered14d": dailyDelivered14d,
        "weeklyDelivered14d": weeklyDelivered14d,
        "PARTIAL_WEEK": partial_week,
        "DATA_MIN": data_min,
        "DATA_MAX": data_max,
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
    }

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {out_path}")
    print(f"DATA_MIN={data_min} DATA_MAX={data_max} PARTIAL_WEEK={partial_week!r}")
    print(f"{len(daily)} days, {len(weekly)} weeks")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
