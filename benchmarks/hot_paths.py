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


def make_vehicle(i: int) -> dict:
    make = ["Toyota", "Honda", "Ford", "Tesla", "Hyundai"][i % 5]
    model = ["Camry", "Accord", "F-150", "Model 3", "Tucson"][i % 5]
    body = ["sedan", "suv", "truck", "sedan", "suv"][i % 5]
    fuel = ["gasoline", "hybrid", "gasoline", "electric", "hybrid"][i % 5]
    return {
        "id": f"BM-{i:07d}",
        "year": 2016 + (i % 10),
        "make": make,
        "model": model,
        "trim": "Base",
        "body_type": body,
        "price": 18_000 + (i % 200) * 300,
        "mileage": 5_000 + (i % 120_000),
        "exterior_color": "black",
        "interior_color": "gray",
        "fuel_type": fuel,
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
    async def run(self, user_input, tool_name, data_context):
        return SimpleNamespace(response=SimpleNamespace(content="ok"))


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


def bench_store_search(records: int, repeats: int) -> tuple[float, float, float]:
    vehicles = [make_vehicle(i) for i in range(records)]
    store = SqliteVehicleStore(":memory:")
    store.upsert_many(vehicles)

    start = time.perf_counter()
    for i in range(repeats):
        make = ["Toyota", "Honda", "Ford", "Tesla", "Hyundai"][i % 5]
        _ = store.search(make=make, price_min=25_000, price_max=42_000, body_type="sedan")
    full_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    for i in range(repeats):
        make = ["Toyota", "Honda", "Ford", "Tesla", "Hyundai"][i % 5]
        _ = store.count_filtered(
            make=make, price_min=25_000, price_max=42_000, body_type="sedan"
        )
        _ = store.search_page(
            make=make, price_min=25_000, price_max=42_000, body_type="sedan", limit=10
        )
    windowed_elapsed = time.perf_counter() - start

    speedup = full_elapsed / max(windowed_elapsed, 1e-9)
    return full_elapsed, windowed_elapsed, speedup


async def bench_search_tool(records: int, repeats: int) -> tuple[float, float]:
    vehicles = [make_vehicle(i) for i in range(records)]
    store = SqliteVehicleStore(":memory:")
    store.upsert_many(vehicles)
    set_store(store)

    cip = NullCIP()
    await search_vehicles_impl(
        cip, make="Toyota", body_type="sedan", price_min=20_000, price_max=50_000
    )

    start = time.perf_counter()
    for _ in range(repeats):
        await search_vehicles_impl(
            cip, make="Toyota", body_type="sedan", price_min=20_000, price_max=50_000
        )
    elapsed = time.perf_counter() - start
    set_store(None)
    return elapsed, (elapsed / max(repeats, 1)) * 1000


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark AutoCIP hot paths.")
    parser.add_argument("--records", type=int, default=80_000)
    parser.add_argument("--repeats", type=int, default=120)
    args = parser.parse_args()

    print("autocip_hot_path_benchmark")
    print(f"records={args.records}")
    print(f"repeats={args.repeats}")

    disk_elapsed, disk_rps = bench_disk_upsert(args.records // 4)
    print(f"disk_upsert_many_seconds={disk_elapsed:.6f}")
    print(f"disk_upsert_many_rows_per_sec={disk_rps:.2f}")

    full_elapsed, windowed_elapsed, speedup = bench_store_search(args.records, args.repeats)
    print(f"store_search_full_seconds={full_elapsed:.6f}")
    print(f"store_search_windowed_seconds={windowed_elapsed:.6f}")
    print(f"store_search_windowed_speedup={speedup:.2f}x")

    tool_elapsed, tool_avg_ms = await bench_search_tool(args.records, args.repeats)
    print(f"tool_search_total_seconds={tool_elapsed:.6f}")
    print(f"tool_search_avg_ms={tool_avg_ms:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
