#!/usr/bin/env python3
"""Performance benchmark for AutoCIP ingestion and search hot paths."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
import time
from types import SimpleNamespace

from auto_mcp.data.inventory import set_store
from auto_mcp.data.store import SqliteVehicleStore
from auto_mcp.tools.search import search_vehicles_impl

MAKES = ["Toyota", "Honda", "Ford", "Tesla", "Hyundai"]
MODELS = ["Camry", "Accord", "F-150", "Model 3", "Tucson"]
BODIES = ["sedan", "suv", "truck", "sedan", "suv"]
FUELS = ["gasoline", "hybrid", "gasoline", "electric", "hybrid"]


def make_vehicle(i: int) -> dict:
    return {
        "id": f"BM-{i:07d}",
        "year": 2016 + (i % 10),
        "make": MAKES[i % 5],
        "model": MODELS[i % 5],
        "trim": "Base",
        "body_type": BODIES[i % 5],
        "price": 18_000 + (i % 200) * 300,
        "mileage": 5_000 + (i % 120_000),
        "exterior_color": "black",
        "interior_color": "gray",
        "fuel_type": FUELS[i % 5],
        "mpg_city": 24,
        "mpg_highway": 31,
        "engine": "2.0L",
        "transmission": "automatic",
        "drivetrain": "fwd",
        "features": ["bluetooth", "backup_camera"],
        "safety_rating": 5,
        "dealer_name": "Benchmark Auto",
        "dealer_location": "Austin, TX" if i % 3 else "Dallas, TX",
        "availability_status": "in_stock",
        "vin": f"VIN{i:014d}",
    }


class NullCIP:
    """Minimal CIP mock that accepts all keyword args from orchestration."""

    async def run(self, user_input, **kwargs):
        return SimpleNamespace(response=SimpleNamespace(content="ok"))


def _make_store(records: int, *, in_memory: bool = True) -> SqliteVehicleStore:
    vehicles = [make_vehicle(i) for i in range(records)]
    store = SqliteVehicleStore(":memory:" if in_memory else "")
    store.upsert_many(vehicles)
    return store


# ── Benchmarks ────────────────────────────────────────────────────────


def bench_disk_upsert(records: int) -> tuple[float, float]:
    vehicles = [make_vehicle(i) for i in range(records)]
    with tempfile.NamedTemporaryFile(prefix="autocip-bench-", suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        store = SqliteVehicleStore(db_path)
        start = time.perf_counter()
        store.upsert_many(vehicles)
        elapsed = time.perf_counter() - start
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except FileNotFoundError:
                pass

    return elapsed, records / max(elapsed, 1e-9)


def bench_store_search(records: int, repeats: int) -> dict[str, float]:
    store = _make_store(records)

    # Full search (returns all rows)
    start = time.perf_counter()
    for i in range(repeats):
        store.search(make=MAKES[i % 5], price_min=25_000, price_max=42_000, body_type="sedan")
    full_elapsed = time.perf_counter() - start

    # Two-query windowed (count + page)
    start = time.perf_counter()
    for i in range(repeats):
        store.count_filtered(
            make=MAKES[i % 5], price_min=25_000, price_max=42_000, body_type="sedan"
        )
        store.search_page(
            make=MAKES[i % 5], price_min=25_000, price_max=42_000, body_type="sedan", limit=10
        )
    two_query_elapsed = time.perf_counter() - start

    # Single-query windowed (COUNT(*) OVER())
    start = time.perf_counter()
    for i in range(repeats):
        store.search_page_with_count(
            make=MAKES[i % 5], price_min=25_000, price_max=42_000, body_type="sedan", limit=10
        )
    single_query_elapsed = time.perf_counter() - start

    return {
        "full": full_elapsed,
        "two_query": two_query_elapsed,
        "single_query": single_query_elapsed,
        "speedup_vs_full": full_elapsed / max(single_query_elapsed, 1e-9),
        "speedup_vs_two_query": two_query_elapsed / max(single_query_elapsed, 1e-9),
    }


async def bench_search_tool(records: int, repeats: int) -> tuple[float, float]:
    store = _make_store(records)
    set_store(store)

    cip = NullCIP()
    # Warmup
    await search_vehicles_impl(
        cip, make="Toyota", body_type="sedan", price_min=20_000, price_max=50_000, raw=True
    )

    start = time.perf_counter()
    for _ in range(repeats):
        await search_vehicles_impl(
            cip, make="Toyota", body_type="sedan", price_min=20_000, price_max=50_000, raw=True
        )
    elapsed = time.perf_counter() - start
    set_store(None)
    return elapsed, (elapsed / max(repeats, 1)) * 1000


def bench_pricing_opportunities(records: int) -> tuple[float, int]:
    """Benchmark get_pricing_opportunities — previously O(n²), now O(n)."""
    store = _make_store(records)
    start = time.perf_counter()
    result = store.get_pricing_opportunities(limit=50)
    elapsed = time.perf_counter() - start
    return elapsed, result["total_opportunities"]


def bench_hot_leads(records: int, lead_events: int) -> tuple[float, int]:
    """Benchmark get_hot_leads with batched sub-queries."""
    store = _make_store(records)

    # Seed lead events
    for i in range(lead_events):
        vid = f"BM-{i % records:07d}"
        actions = ["viewed", "compared", "financed", "test_drive", "contact_dealer"]
        store.record_lead(
            vid, actions[i % len(actions)],
            lead_id=f"bench-lead-{i % 20:03d}",
            customer_name=f"Customer {i % 20}",
            customer_contact=f"cust{i % 20}@bench.test",
        )

    start = time.perf_counter()
    leads = store.get_hot_leads(limit=20, min_score=0.0, days=90)
    elapsed = time.perf_counter() - start
    return elapsed, len(leads)


def bench_inventory_aging(records: int) -> tuple[float, int]:
    """Benchmark get_inventory_aging_report with single JOIN query."""
    store = _make_store(records)
    start = time.perf_counter()
    report = store.get_inventory_aging_report(min_days_on_lot=0, limit=100)
    elapsed = time.perf_counter() - start
    return elapsed, report["total_units_considered"]


# ── Main ──────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark AutoCIP hot paths.")
    parser.add_argument("--records", type=int, default=80_000)
    parser.add_argument("--repeats", type=int, default=120)
    args = parser.parse_args()

    print("autocip_hot_path_benchmark")
    print(f"records={args.records}")
    print(f"repeats={args.repeats}")
    print()

    # 1. Disk upsert
    disk_elapsed, disk_rps = bench_disk_upsert(args.records // 4)
    print(f"disk_upsert_many_seconds={disk_elapsed:.6f}")
    print(f"disk_upsert_many_rows_per_sec={disk_rps:.0f}")
    print()

    # 2. Search: full vs two-query vs single-query
    search = bench_store_search(args.records, args.repeats)
    print(f"store_search_full_seconds={search['full']:.6f}")
    print(f"store_search_two_query_seconds={search['two_query']:.6f}")
    print(f"store_search_single_query_seconds={search['single_query']:.6f}")
    print(f"store_search_speedup_vs_full={search['speedup_vs_full']:.2f}x")
    print(f"store_search_speedup_vs_two_query={search['speedup_vs_two_query']:.2f}x")
    print()

    # 3. Search tool (raw mode, no LLM)
    tool_elapsed, tool_avg_ms = await bench_search_tool(args.records, args.repeats)
    print(f"tool_search_total_seconds={tool_elapsed:.6f}")
    print(f"tool_search_avg_ms={tool_avg_ms:.4f}")
    print()

    # 4. Pricing opportunities (was O(n²), now O(n))
    pricing_elapsed, pricing_count = bench_pricing_opportunities(min(args.records, 10_000))
    print(f"pricing_opportunities_seconds={pricing_elapsed:.6f}")
    print(f"pricing_opportunities_count={pricing_count}")
    print()

    # 5. Hot leads (batched sub-queries)
    leads_elapsed, leads_count = bench_hot_leads(min(args.records, 5_000), 200)
    print(f"hot_leads_seconds={leads_elapsed:.6f}")
    print(f"hot_leads_count={leads_count}")
    print()

    # 6. Inventory aging (single JOIN)
    aging_elapsed, aging_count = bench_inventory_aging(min(args.records, 10_000))
    print(f"inventory_aging_seconds={aging_elapsed:.6f}")
    print(f"inventory_aging_units={aging_count}")


if __name__ == "__main__":
    asyncio.run(main())
