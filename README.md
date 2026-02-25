# AutoCIP

An MCP server that turns car conversations into real outcomes — for shoppers and dealers.

AutoCIP is built on [CIP](https://github.com/Cole-Cant-Code/CIP-Customer-Intelligence-Protocol), a protocol for scaffolded LLM reasoning with domain guardrails. It connects a specialist AI to live inventory, lead signals, and dealer analytics so conversations don't dead-end at "here are some results."

---

## The idea

Most AI car tools are search boxes with a chatbot bolted on. They answer questions but don't reason about them — they can't shape a response based on whether you're a nervous first-time buyer or a dealer repricing stale inventory.

AutoCIP is different because it separates **what the AI knows** from **how it thinks about it**.

Every response is shaped by a **scaffold** — a YAML reasoning framework that tells the specialist LLM how to approach a specific task. A vehicle comparison scaffold structures trade-off analysis. A financing scaffold enforces estimate framing and blocks guarantee language. A dealer lead scaffold prioritizes by intent score and recency.

The result: responses that feel like they came from someone who understands both the data and the situation.

---

## How it works

```
┌──────────────────────────────────┐
│         Outer LLM (Boss)         │
│  Holds conversation context.     │
│  Decides what to ask and how.    │
└───────────────┬──────────────────┘
                │  tool call
                ▼
┌──────────────────────────────────┐
│        AutoCIP MCP Server        │
│                                  │
│  1. Fetches data from store      │
│  2. Selects reasoning scaffold   │
│  3. Shapes specialist behavior   │
│  4. Runs inner LLM               │
│  5. Enforces guardrails          │
│  6. Returns structured response  │
└───────────────┬──────────────────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 SQLite      Scaffolds    Guardrails
 inventory   (31 YAML     (blocked phrases,
 + leads     reasoning    regex policies,
 + sales     frameworks)  disclaimers)
```

Two LLMs are in play. The **outer LLM** (Claude, in your chat) holds the full conversation — who you are, what you've asked, what matters to you. The **inner LLM** (the specialist) is a domain expert that gets briefed per-task by a scaffold. It knows cars and financing deeply but has no memory between calls. The outer LLM orchestrates; the specialist executes.

---

## What scaffolds actually do

A scaffold isn't a prompt template. It's a structured reasoning framework:

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

This shapes **how the specialist thinks**, not just what it says. The reasoning steps enforce structure. The output calibration controls what appears and what doesn't. The guardrails catch violations after generation.

There are 31 scaffolds covering search, comparison, financing, market pricing, lead analysis, inventory aging, funnel metrics, and more — including dealer-specific variants that shift tone and detail level for professional use.

---

## Guardrails as a design principle

AutoCIP is opinionated about what AI should and shouldn't do in car shopping.

**Blocked by design:**
- Purchase pressure — *"you should definitely buy this"*
- Financing guarantees — *"your APR will be 4.5%"*
- Legal advice — *"legally you should..."*
- Mechanical promises — *"this engine will last 200k miles"*

**Enforced by design:**
- Financial outputs are framed as estimates, never promises
- Disclaimers are appended where appropriate, automatically
- Regex policies catch patterns like APR promises and credit score diagnoses
- Violations are redacted post-generation, not just prompted against

This isn't a safety disclaimer — it's the architecture. The guardrail system runs **after** the specialist generates its response, catching things the prompt couldn't prevent.

---

## For shoppers

```
"Compare these three vehicles and include the tradeoffs."
"What would 48 vs 72 month financing look like with $5k down?"
"Is this listing priced above or below market?"
"What's the real out-the-door cost with taxes and fees in Texas?"
"Save this search and bookmark that RAV4 for me."
"Can I put a 48-hour hold on this one while I think?"
```

The full buyer flow: **discovery** → **evaluation** → **financial modeling** → **conversion** → **post-purchase**. Search by filters, location, or VIN. Compare side-by-side. Model financing scenarios. Check availability, message the dealer, reserve a vehicle, submit a deposit, schedule service after purchase.

## For dealers

```
"Show my top 10 hottest leads this week."
"Walk me through lead L-0042's full timeline."
"Which units have been sitting 45+ days with low engagement?"
"What should I reprice, promote, or hold?"
"What are my funnel conversion rates by source channel?"
```

Lead profiles with identity stitching and intent scoring. Inventory aging and velocity reports. Pricing opportunity analysis. Sale recording that closes the loop — so you can measure the full funnel from first view to final sale.

---

## Quick start

```bash
git clone https://github.com/Cole-Cant-Code/Consumer-Intelligence-Protocol-Automotive.git
cd Consumer-Intelligence-Protocol-Automotive

# Install (Python 3.11+)
uv sync --all-extras

# Test
uv run pytest tests/ -v

# Run
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

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (default provider) | Powers the inner specialist LLM |
| `OPENAI_API_KEY` | If using OpenAI provider | Alternative specialist LLM |
| `AUTO_DEV_API_KEY` | For API import | Bulk import from Auto.dev |

---

## Project structure

```
auto_mcp/
├── server.py                  # FastMCP entry point (43 tools)
├── config.py                  # Domain config, prohibited patterns, regex policies
├── data/
│   ├── store.py               # SQLite schema — inventory, leads, sales
│   ├── inventory.py           # Public data facade
│   ├── journey.py             # Customer journey state
│   └── seed.py                # Demo vehicles
├── tools/                     # 20 modules, one per tool family
│   ├── search.py              # Vehicle search
│   ├── compare.py             # Side-by-side comparison
│   ├── financing.py           # Payment estimates
│   ├── financing_scenarios.py # Multi-scenario modeling
│   ├── details.py             # Vehicle specs
│   ├── market.py              # Market price context
│   ├── history.py             # Vehicle history
│   ├── ownership.py           # Cost of ownership
│   ├── warranty.py            # Warranty info
│   ├── recommendations.py     # Similar vehicles
│   ├── location_search.py     # Geo search
│   ├── vin_search.py          # VIN lookup
│   ├── availability.py        # Stock checks
│   ├── scheduling.py          # Test drives
│   ├── engagement.py          # Saves, favorites, reservations, dealer contact
│   ├── dealer_intelligence.py # Leads, aging, pricing, funnel
│   ├── sales.py               # Sale recording
│   ├── ingestion.py           # CRUD + VIN normalization + API import
│   ├── stats.py               # Inventory analytics
│   └── orchestration.py       # Boss-controlled specialist routing
├── scaffolds/                 # 31 YAML reasoning frameworks
│   ├── vehicle_comparison.yaml
│   ├── financing_scenarios.yaml
│   ├── lead_hotlist.yaml
│   └── ...
└── ingestion/
    └── pipeline.py            # Field normalization, VIN decode
```

## Development

```bash
uv run ruff check auto_mcp tests    # lint
uv run pytest tests -q               # 252 tests
```

## License

Business Source License 1.1.

[LICENSE](LICENSE) · [LICENSE-APACHE](LICENSE-APACHE) · [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md) · [TRADEMARKS.md](TRADEMARKS.md)

Licensing contact: `licensing@manticthink.com`
