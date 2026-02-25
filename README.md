# Consumer-Intelligence-Protocol-Automotive (AutoCIP)

**A vehicle shopping assistant MCP server built on [CIP](https://github.com/Cole-Cant-Code/CIP-Customer-Intelligence-Protocol).**

AutoCIP connects an LLM to a live vehicle inventory so it can search, compare, and reason about real cars — complete with guardrails that prevent it from making purchase decisions, guaranteeing financing terms, or giving legal advice.

```
User:  "What SUVs are near Austin under $40k?"
AutoCIP → searches inventory → CIP scaffold → guardrail-checked response
```

## What it does

| Tool | Description |
|------|-------------|
| `search_vehicles` | Filter by make, model, year, price, body type, fuel type |
| `get_vehicle_details` | Full specs for a vehicle by ID |
| `compare_vehicles` | Side-by-side comparison of 2-3 vehicles |
| `estimate_financing` | Monthly payment estimates (with disclaimers) |
| `estimate_trade_in` | Trade-in value based on year, make, model, mileage, condition |
| `check_availability` | Stock status + dealer info |
| `schedule_test_drive` | Request a test drive appointment |
| `assess_purchase_readiness` | Evaluate readiness based on budget, financing, insurance |
| `upsert_vehicle` | Add or update a single vehicle in inventory |
| `bulk_upsert_vehicles` | Batch add/update vehicles |
| `remove_vehicle` | Remove a vehicle by ID |

The first 8 tools go through CIP's reasoning framework (scaffold selection, data context injection, guardrail enforcement). The last 3 are pure CRUD for inventory ingestion.

## Architecture

```
MCP Client (Claude, etc.)
    │
    ▼
┌─────────────────────────────────┐
│  server.py  (FastMCP, 11 tools) │
└──────┬──────────────────────────┘
       │
  ┌────┴────┐
  │         │
  ▼         ▼
tools/    data/
  │         │
  │    ┌────┴────┐
  │    │         │
  │  inventory   store.py
  │  .py (facade) (SQLite + WAL)
  │    │         │
  │    └────┬────┘
  │         │
  ▼         ▼
CIP Protocol    seed.py
(scaffolds +    (32 demo vehicles)
 guardrails)
```

**Key design choices:**

- **SQLite with WAL mode** — concurrent reads during writes, no external DB server needed
- **`VehicleStore` protocol** — swap SQLite for Postgres (or anything) without changing tool code
- **Facade pattern** in `inventory.py` — all existing tools import from here; the switch from hardcoded list to SQLite required zero changes in any tool file
- **UPSERT semantics** — dealers can push the same vehicle repeatedly without duplicates
- **Auto-seeding** — empty DB gets populated with 32 demo vehicles on first access

## Guardrails

CIP enforces domain-specific safety constraints:

- **No purchase pressure** — blocks "you should definitely buy" language
- **No financial guarantees** — catches APR promises, approval guarantees
- **No legal advice** — prevents unauthorized legal guidance
- **No mechanical diagnosis** — stops engine life guarantees
- **Regex policies** — catches patterns like "your APR will be 4.5%"

Flagged content gets redacted before reaching the user.

## Quick start

```bash
# Clone
git clone https://github.com/Cole-Cant-Code/Consumer-Intelligence-Protocol-Automotive.git
cd Consumer-Intelligence-Protocol-Automotive

# Install (requires Python 3.11+)
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Start the MCP server
export ANTHROPIC_API_KEY="sk-ant-..."
uv run mcp run auto_mcp/server.py
```

### Connect to Claude Desktop

Add to your Claude Desktop MCP config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "autocip": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Consumer-Intelligence-Protocol-Automotive", "mcp", "run", "auto_mcp/server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

### Live inventory ingestion

Push vehicles from a dealer feed, script, or another MCP client:

```python
# Single vehicle
upsert_vehicle(vehicle={
    "id": "DEALER-001",
    "year": 2025,
    "make": "Rivian",
    "model": "R1S",
    "trim": "Adventure",
    "body_type": "suv",
    "price": 78000,
    "dealer_location": "Austin, TX",
    # ... all 22 fields
})

# Batch
bulk_upsert_vehicles(vehicles=[...])

# Remove sold vehicles
remove_vehicle(vehicle_id="DEALER-001")
```

The DB path defaults to `auto_mcp/data/inventory.db`. Override with `AUTOCIP_DB_PATH` env var.

## Development

```bash
# Lint
uv run ruff check auto_mcp/ tests/

# Test with coverage
uv run pytest tests/ -v --cov=auto_mcp

# Test count: 86 (56 original + 30 new for store/ingestion)
```

## Project structure

```
auto_mcp/
├── server.py              # FastMCP server — 11 tool registrations
├── config.py              # CIP domain config + guardrails
├── data/
│   ├── inventory.py       # Thin facade (get_vehicle, search_vehicles)
│   ├── store.py           # VehicleStore protocol + SqliteVehicleStore
│   └── seed.py            # 32 demo vehicles + seed_demo_data()
├── tools/
│   ├── search.py          # Search with CIP reasoning
│   ├── details.py         # Vehicle details with CIP reasoning
│   ├── compare.py         # Side-by-side comparison
│   ├── availability.py    # Stock check + dealer info
│   ├── financing.py       # Payment + trade-in estimates
│   ├── scheduling.py      # Test drive + purchase readiness
│   └── ingestion.py       # CRUD: upsert, bulk_upsert, remove
└── scaffolds/             # 9 YAML reasoning frameworks
    ├── vehicle_search.yaml
    ├── vehicle_details.yaml
    └── ...
```

## License

AutoCIP is licensed under the Business Source License 1.1. See
[`LICENSE`](LICENSE).

Additional licensing docs:

- Apache 2.0 reference text: [`LICENSE-APACHE`](LICENSE-APACHE)
- Commercial licensing information: [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md)
- Trademark policy: [`TRADEMARKS.md`](TRADEMARKS.md)
- Licensing contact: `licensing@manticthink.com`
