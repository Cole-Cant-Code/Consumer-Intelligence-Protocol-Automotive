# AutoCIP

Scaffold-driven MCP server that turns car conversations into real outcomes — for shoppers and dealers

[![License: BUSL 1.1](https://img.shields.io/badge/license-BUSL--1.1-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org)
[![MCP](https://img.shields.io/badge/protocol-MCP-blueviolet.svg)](https://modelcontextprotocol.io)
[![Tests: 415](https://img.shields.io/badge/tests-415-brightgreen.svg)](tests/)

## License In 30 Seconds

AutoCIP is source-available under Business Source License 1.1 (`BUSL-1.1`): you can read, modify, and use it internally, but operating a competing commercial vehicle marketplace service requires a commercial license until each version's Change Date (four years after first public release), after which that version converts to Apache-2.0. See [LICENSE](LICENSE) and [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md).

GitHub may show this repository as "Other/NOASSERTION" instead of `BUSL-1.1`; this is expected for BUSL text with project-specific Additional Use Grant language. The authoritative terms are in [LICENSE](LICENSE).

```
You:     "Compare the Camry and Accord, then show me financing at 48 vs 72 months with $5k down."

AutoCIP:  Selects vehicle_comparison scaffold → structures trade-off analysis
          Selects financing_scenarios scaffold → models both terms, frames as estimates
          Guardrails enforce: no purchase pressure, no APR promises, disclaimers attached

Result:  A response shaped by how to think about the problem, not just what data to return.
```

> **Domain application; consumes CIP APIs only for scoring and orchestration.** AutoCIP never imports mantic-thinking directly — all multi-signal detection flows through CIP's adapter layer.

---

## Why this exists

Most AI car tools are search boxes with a chatbot on top. They answer questions but don't *reason* about them — they can't shape a response based on whether you're a nervous first-time buyer or a dealer repricing stale inventory.

AutoCIP separates **what the AI knows** from **how it thinks about it**.

Every tool call is routed through a **scaffold** — a YAML reasoning framework that tells a specialist LLM how to approach a specific task. A comparison scaffold structures trade-off analysis. A financing scaffold enforces estimate framing and blocks guarantee language. A dealer lead scaffold prioritizes by intent score and recency.

The result: 52 tools, 35 reasoning frameworks, and a guardrail system that runs *after* generation — not just in the prompt.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│            Outer LLM (Claude / GPT)          │
│                                              │
│  Holds conversation context. Decides what    │
│  to ask. Can override scaffold, policy,      │
│  and provider per tool call.                 │
└─────────────────────┬────────────────────────┘
                      │ MCP tool call
                      ▼
┌──────────────────────────────────────────────┐
│              AutoCIP MCP Server              │
│                                              │
│  1. Resolve provider (anthropic / openai)    │
│  2. Fetch data from SQLite store             │
│  3. Select + load YAML scaffold              │
│  4. Brief the inner specialist LLM           │
│  5. Run specialist, get response             │
│  6. Enforce guardrails (regex + blocklist)   │
│  7. Return shaped response (or raw JSON)     │
│                                              │
│  ┌────────────┬────────────┬──────────────┐  │
│  │  SQLite    │ Scaffolds  │  Guardrails  │  │
│  │  vehicles  │ 35 YAML    │  prohibited  │  │
│  │  leads     │ reasoning  │  phrases,    │  │
│  │  sales     │ frameworks │  regex,      │  │
│  │  profiles  │            │  redaction   │  │
│  └────────────┴────────────┴──────────────┘  │
└──────────────────────────────────────────────┘
```

**Two LLMs are in play.** The outer LLM (in your chat) holds the full conversation and orchestrates. The inner LLM (the specialist) is a domain expert briefed per-task by a scaffold — it knows cars and financing deeply but has no memory between calls. The outer LLM decides *what* to ask; the specialist decides *how* to answer it.

> **[Interactive architecture map](docs/architecture-map.html)** — open `docs/architecture-map.html` in a browser for a zoomable, expandable visualization of the full system: all 52 tools, 35 scaffolds, guardrails, lead funnel, and orchestration overrides.

---

## Tools

52 MCP tools across 10 categories. Every CIP-routed tool accepts `raw=True` to bypass the specialist and get structured JSON directly.

### Shopper tools

| Tool | What it does |
|------|-------------|
| `search_vehicles` | Filter by make, model, year, price, body type, fuel type with pagination |
| `search_by_location` | Geo search within radius of a ZIP code |
| `search_by_vin` | Look up a specific 17-character VIN |
| `get_vehicle_details` | Full specs and information for a vehicle |
| `compare_vehicles` | Side-by-side comparison of 2-3 vehicles |
| `get_similar_vehicles` | Recommend alternatives, optionally biased toward lower price |
| `get_vehicle_history` | Title, accidents, ownership, recalls |
| `get_market_price_context` | Market positioning and deal quality assessment |
| `estimate_financing` | Monthly payment estimate for a single scenario |
| `compare_financing_scenarios` | Matrix of down payments x loan terms |
| `estimate_trade_in` | Trade-in value by year, make, model, mileage, condition |
| `estimate_out_the_door_price` | Total price with taxes, title, registration, doc fees |
| `estimate_cost_of_ownership` | Fuel, maintenance, insurance over N years |
| `estimate_insurance` | Insurance cost range for a vehicle + driver profile |
| `get_warranty_info` | Warranty coverage windows |
| `check_availability` | Stock check with dealer info |
| `assess_purchase_readiness` | Readiness assessment based on budget, financing, trade-in status |

### Auto.dev tools

| Tool | What it does |
|------|-------------|
| `get_autodev_overview` | Auto.dev account/API usage overview context |
| `get_autodev_vin_decode` | Decode VIN data from Auto.dev |
| `get_autodev_listings` | Fetch listings by VIN or search filters (ZIP/distance/make/model/price range/page/limit) |
| `get_autodev_vehicle_photos` | Fetch vehicle photo assets by VIN or inventory vehicle ID |

### Orchestration resources

| Resource/Prompt | What it does |
|------|-------------|
| `autocip://orchestration/entry` | Exposes orchestration entry guidance with embedded scaffold catalog |
| `autocip://scaffolds/catalog` | Lists scaffold IDs and routing hints for `scaffold_id` selection |
| `orchestration_entry_prompt` | Prompt-formatted orchestration briefing and scaffold catalog |

### NHTSA safety tools

| Tool | What it does |
|------|-------------|
| `get_nhtsa_recalls` | NHTSA recall data by VIN, make/model/year, or inventory vehicle ID |
| `get_nhtsa_complaints` | NHTSA consumer complaints by VIN, make/model/year, or inventory vehicle ID |
| `get_nhtsa_safety_ratings` | NHTSA crash test safety ratings by VIN, make/model/year, or inventory vehicle ID |

### Engagement tools

| Tool | What it does |
|------|-------------|
| `save_search` | Persist a named search for later |
| `list_saved_searches` | Retrieve saved searches |
| `save_favorite` | Bookmark a vehicle with optional note |
| `list_favorites` | Retrieve bookmarked vehicles |
| `reserve_vehicle` | Soft hold (default 48h) |
| `contact_dealer` | Send a question to the listing dealer |
| `submit_purchase_deposit` | Begin purchase with deposit and paperwork intake |
| `schedule_test_drive` | Request a test drive appointment |
| `schedule_service` | Post-purchase service appointment |
| `request_follow_up` | Request dealer follow-up after purchase |

### Dealer intelligence tools

| Tool | What it does |
|------|-------------|
| `get_hot_leads` | Highest-intent leads ranked by engagement score |
| `get_lead_detail` | Full timeline and score breakdown for a lead |
| `get_lead_analytics` | Engagement analytics over a period |
| `get_inventory_aging_report` | Stale units by days on lot and velocity |
| `get_pricing_opportunities` | Overpriced, underpriced, and aging units to act on |
| `get_funnel_metrics` | Closed-loop conversion from view through sale, with optional source/channel breakdown |
| `get_inventory_stats` | Aggregate inventory coverage, pricing, freshness |
| `record_sale` | Record a completed sale and link to lead — closes the funnel loop |

### Escalation tools

| Tool | What it does |
|------|-------------|
| `get_escalations` | Pending lead escalation alerts — threshold crossings detected in real time |
| `acknowledge_escalation` | Mark an escalation as delivered/acknowledged |

### Data management tools

| Tool | What it does |
|------|-------------|
| `upsert_vehicle` | Add or update a single vehicle |
| `bulk_upsert_vehicles` | Batch upsert |
| `remove_vehicle` | Delete a vehicle by ID |
| `expire_stale_listings` | TTL-based cleanup of expired listings |
| `record_lead` | Record engagement event with identity stitching |
| `bulk_import_from_api` | Import from Auto.dev API (supports NHTSA VIN decoding) |

### Provider tools

| Tool | What it does |
|------|-------------|
| `set_llm_provider` | Switch specialist to `anthropic` or `openai` at runtime |
| `get_llm_provider` | Show current provider, model, and pool state |

---

## Scaffolds

A scaffold isn't a prompt template. It's a structured reasoning framework that shapes *how the specialist thinks*:

```yaml
# scaffolds/vehicle_comparison.yaml (abbreviated)

framing:
  role: >
    You are a balanced automotive comparison analyst who presents
    objective trade-offs without favoring any particular choice.
  tone: neutral

reasoning_framework:
  steps:
    - Identify key comparison dimensions
    - Present a structured spec table
    - Analyze trade-offs per dimension
    - Summarize which buyer profile each vehicle suits

output_calibration:
  must_include:
    - Comparison table with key specifications
    - Trade-off analysis for each major category
  never_include:
    - Declaring one vehicle the clear winner
    - Subjective brand loyalty statements

guardrails:
  disclaimers:
    - Based on listed specs, not real-world performance.
    - Test drive both vehicles before deciding.
  prohibited_actions:
    - Do not declare one vehicle objectively better
```

The `reasoning_framework` enforces structure. The `output_calibration` controls what appears. The `guardrails` catch violations after generation.

35 scaffolds covering search, comparison, financing, Auto.dev/NHTSA data, market pricing, lead analysis, inventory aging, funnel metrics, escalation alerts, and more — including dealer-specific variants that shift tone and detail level for professional use.

<details>
<summary>All 35 scaffolds</summary>

| Scaffold | Purpose |
|----------|---------|
| `availability_check` | Stock check with context |
| `availability_check_dealer` | Dealer-facing stock check |
| `autodev_data` | Auto.dev overview, VIN, listings, and photo data framing |
| `financing_overview` | Single-scenario payment framing |
| `financing_scenarios` | Multi-scenario comparison matrix |
| `funnel_metrics` | Conversion funnel analysis |
| `general_advice` | Default catch-all reasoning |
| `insurance_estimate` | Insurance cost range framing |
| `inventory_aging_report` | Stale inventory analysis |
| `inventory_stats` | Aggregate inventory metrics |
| `lead_analytics` | Engagement analytics reporting |
| `lead_detail` | Individual lead deep-dive |
| `lead_escalation` | Real-time threshold crossing alerts for sales teams |
| `lead_hotlist` | Hot lead prioritization |
| `location_search` | Geo-search result framing |
| `market_price_context` | Market positioning for shoppers |
| `market_price_context_dealer` | Market positioning for dealers |
| `nhtsa_safety` | NHTSA recalls, complaints, and safety ratings presentation |
| `orchestration_entry` | Lightweight pre-tool orchestration assessment |
| `out_the_door_price` | Total cost breakdown |
| `ownership_cost` | Long-term cost projection |
| `pricing_opportunities` | Pricing action recommendations |
| `purchase_readiness` | Buyer readiness assessment |
| `similar_vehicles` | Alternative recommendations |
| `test_drive_schedule` | Test drive booking context |
| `trade_in_estimate` | Trade-in value framing |
| `vehicle_comparison` | Side-by-side trade-off analysis |
| `vehicle_comparison_dealer` | Dealer-facing comparison |
| `vehicle_details` | Spec sheet presentation |
| `vehicle_details_dealer` | Dealer-facing spec view |
| `vehicle_history` | History report framing |
| `vehicle_search` | Search result presentation |
| `vehicle_search_dealer` | Dealer-facing search results |
| `vin_lookup` | VIN decode presentation |
| `warranty_info` | Warranty coverage framing |

</details>

---

## Guardrails

AutoCIP is opinionated about what AI should and shouldn't do in car shopping. The guardrail system runs **after** the specialist generates its response, catching things the prompt couldn't prevent.

**Blocked by design:**
- Purchase pressure — *"you should definitely buy this"*
- Financing guarantees — *"your APR will be 4.5%"*
- Legal advice — *"legally you should..."*
- Mechanical promises — *"this engine will last 200k miles"*

**Enforced by design:**
- Financial outputs framed as estimates, never promises
- Disclaimers appended automatically where appropriate
- Regex policies catch APR promises and credit score diagnoses
- Violations redacted post-generation: `[Removed: contains prohibited automotive advice]`

---

## Orchestration overrides

Every CIP-routed tool accepts four optional parameters that let the outer LLM control the specialist per-call:

| Parameter | What it does |
|-----------|-------------|
| `provider` | Route to a specific provider (`anthropic` or `openai`) for this call |
| `scaffold_id` | Override the auto-selected scaffold with a specific one |
| `policy` | Inject a policy constraint the specialist must follow |
| `context_notes` | Pass cross-domain context from the outer LLM's conversation |
| `raw` | Bypass the specialist entirely — return structured JSON data |

This means the outer LLM isn't just calling tools — it's *directing* the specialist. It can switch reasoning frameworks mid-conversation, inject situational context, or drop to raw data when it needs to compute something itself.

---

## Lead scoring

Engagement events are weighted to produce an intent score per lead:

| Action | Weight |
|--------|--------|
| Viewed listing | 1.0 |
| Compared vehicles | 3.0 |
| Contacted dealer | 4.0 |
| Checked availability | 5.0 |
| Ran financing | 6.0 |
| Scheduled test drive | 8.0 |
| Reserved vehicle | 9.0 |
| Submitted deposit | 10.0 |

Leads are stitched across sessions via `lead_id`, `customer_id`, and `session_id`. The funnel tracks five stages: **discovery** → **consideration** → **financial** → **intent** → **outcome**.

When a lead's cumulative score crosses a threshold (cold → warm at 10, warm → hot at 22), an **escalation** is generated synchronously inside `record_lead()` — no polling, no background threads. Escalations are stored, deduplicated, and surfaced through `get_escalations` so dealers get alerted the moment a lead heats up.

---

## Quick start

```bash
git clone https://github.com/Cole-Cant-Code/Consumer-Intelligence-Protocol-Automotive.git
cd Consumer-Intelligence-Protocol-Automotive

# Install (Python 3.11+ required)
uv sync --all-extras

# Run tests
uv run pytest tests/ -v    # 415 tests

# Start the server
export ANTHROPIC_API_KEY="sk-ant-..."
uv run mcp run auto_mcp/server.py
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "autocip": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/Consumer-Intelligence-Protocol-Automotive",
        "mcp",
        "run",
        "auto_mcp/server.py"
      ],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

<details>
<summary>Connect to Claude Code (CLI)</summary>

```bash
claude mcp add-json autocip '{
  "command": "uv",
  "args": [
    "run",
    "--directory",
    "/path/to/Consumer-Intelligence-Protocol-Automotive",
    "mcp",
    "run",
    "auto_mcp/server.py"
  ],
  "env": {
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}'
```

</details>

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (default provider) | Powers the inner specialist LLM (claude-sonnet-4-6) |
| `OPENAI_API_KEY` | If using OpenAI provider | Alternative specialist (gpt-4o) |
| `AUTO_DEV_API_KEY` | For Auto.dev tools/import | Auto.dev overview/VIN/listings/photos + bulk import |
| `CIP_LLM_PROVIDER` | No | Override default provider (`anthropic` or `openai`) |
| `CIP_LLM_MODEL` | No | Override default model for the active provider |
| `AUTOCIP_DB_PATH` | No | Override default SQLite database path |

---

## Project structure

```
auto_mcp/
├── server.py              # FastMCP entry point — 52 tools, provider pool, orchestration wiring
├── config.py              # DomainConfig — prohibited patterns, regex guardrails, redaction
├── normalization.py       # Canonical field normalization (price, body type, fuel type) — shared by ingestion paths
├── data/
│   ├── store.py           # SQLite (WAL) — vehicles, leads, lead_profiles, sales, ingestion_log
│   ├── inventory.py       # Public data facade (singleton)
│   ├── journey.py         # In-memory customer journey state (saves, favorites, reservations)
│   └── seed.py            # 25+ demo vehicles across 7 Texas locations
├── clients/
│   ├── autodev.py         # Shared async Auto.dev API client (overview, VIN, listings, photos)
│   └── nhtsa.py           # Shared async NHTSA API client (recalls, complaints, ratings, VIN decode)
├── tools/                 # 23 modules, one per tool family
│   ├── orchestration.py   # run_tool_with_orchestration() — scaffold selection + raw bypass
│   ├── search.py          # Vehicle search
│   ├── compare.py         # Side-by-side comparison
│   ├── financing.py       # Payment + trade-in estimates
│   ├── financing_scenarios.py
│   ├── details.py         # Vehicle specs
│   ├── market.py          # Market price context
│   ├── history.py         # Vehicle history
│   ├── ownership.py       # Cost of ownership, insurance, OTD price
│   ├── warranty.py        # Warranty info
│   ├── recommendations.py # Similar vehicles
│   ├── location_search.py # Geo search
│   ├── vin_search.py      # VIN lookup
│   ├── availability.py    # Stock checks
│   ├── scheduling.py      # Test drives + purchase readiness
│   ├── engagement.py      # Saves, favorites, reservations, dealer contact, deposits
│   ├── dealer_intelligence.py  # Leads, aging, pricing, funnel
│   ├── escalation.py      # Escalation alerts + acknowledgement
│   ├── sales.py           # Sale recording
│   ├── autodev.py         # Auto.dev overview, VIN decode, listings, photos
│   ├── nhtsa.py           # NHTSA recalls, complaints, safety ratings
│   ├── ingestion.py       # CRUD + VIN normalization + API import
│   └── stats.py           # Inventory + lead analytics
├── escalation/
│   ├── detector.py        # Pure threshold-crossing detection logic
│   └── store.py           # SQLite escalation persistence + deduplication
├── scaffolds/             # 35 YAML reasoning frameworks
│   ├── vehicle_comparison.yaml
│   ├── financing_scenarios.yaml
│   ├── lead_hotlist.yaml
│   └── ...
└── ingestion/
    └── pipeline.py        # Auto.dev + NHTSA field normalization, VIN decode
```

---

## Development

```bash
uv run ruff check auto_mcp tests    # lint
uv run pytest tests -q               # 415 tests
uv run pytest tests -v --tb=short    # verbose with tracebacks
```

Built on [CIP (Customer Intelligence Protocol)](https://github.com/Cole-Cant-Code/CIP-Customer-Intelligence-Protocol) — the scaffolded reasoning framework that powers the inner specialist.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Open an issue first for anything beyond a typo fix.

## License

Business Source License 1.1 — converts to Apache 2.0 after four years.

[LICENSE](LICENSE) · [LICENSE-APACHE](LICENSE-APACHE) · [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md) · [TRADEMARKS.md](TRADEMARKS.md)

Licensing contact: `licensing@manticthink.com`
