# Consumer-Intelligence-Protocol-Automotive (AutoCIP)

AutoCIP is an MCP server that helps people shop for cars and helps dealers run better operations.

Built on [CIP](https://github.com/Cole-Cant-Code/CIP-Customer-Intelligence-Protocol), it connects an LLM to live inventory, lead activity, and dealer analytics so conversations can move from "just browsing" to real outcomes.

## Why this exists
Most car tools do one of these well:
- help buyers browse
- help dealers manage inventory
- help sales teams track outcomes

AutoCIP combines all three in one flow.

## What this feels like in real life

### If you're a shopper
You can ask things like:
- "Show me SUVs under $40k near 78701."
- "What’s similar to this vehicle but cheaper?"
- "What would this cost me monthly with different down payments?"
- "What’s the out-the-door price with taxes and fees?"
- "Can I reserve this one or message the dealer first?"

### If you're a dealer
You can do things like:
- import and manage inventory
- see which leads are hottest right now
- inspect one lead’s timeline and intent score
- spot stale/overpriced units before they rot on lot
- record closed sales and measure full funnel conversion

## Core capabilities (human version)

### Buyer journey
- Discovery: search, location search, VIN lookup, similar vehicles, saved searches, favorites
- Evaluation: detailed specs, comparison, vehicle history summary, market price context, ownership cost
- Financial: financing estimate, financing scenario comparison, insurance estimate, out-the-door estimate, trade-in estimate
- Conversion: availability checks, dealer messaging, vehicle holds, test-drive requests, deposit capture
- Post-purchase: service request, warranty overview, follow-up requests

### Dealer intelligence
- Lead profiles with identity stitching and scoring
- Hot lead ranking and per-lead timeline details
- Inventory aging + velocity reports
- Pricing opportunity recommendations (reprice / promote / hold)
- Sale recording + closed-loop funnel analytics (discovery -> outcome)

### Inventory operations
- single and bulk upsert
- API ingestion via Auto.dev
- stale listing expiration
- inventory and lead aggregate analytics

## Example prompts

### Shopper prompts
- "Compare these three vehicles and include the tradeoffs."
- "Estimate 48 vs 72 month financing with $5k and $10k down."
- "Is this listing above or below market?"

### Dealer prompts
- "Show my top 10 hot leads in the last 14 days."
- "Which units are 45+ days on lot with low lead velocity?"
- "What are my funnel conversion rates this month by source channel?"

## Safety and guardrails
AutoCIP is designed to be useful without pretending to be a lawyer, lender, or mechanic.

It blocks or redacts unsafe patterns like:
- purchase pressure ("you should definitely buy this")
- guaranteed financing outcomes
- legal advice
- mechanical guarantees

Financial and risk outputs are presented as estimates, not promises.

## Quick start

```bash
# Clone

git clone https://github.com/Cole-Cant-Code/Consumer-Intelligence-Protocol-Automotive.git
cd Consumer-Intelligence-Protocol-Automotive

# Install (Python 3.11+)
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Start MCP server
export ANTHROPIC_API_KEY="sk-ant-..."
uv run mcp run auto_mcp/server.py
```

## Connect to Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

## Dealer workflow snippet

```python
# 1) Track lead behavior
record_lead(vehicle_id="VH-001", action="viewed", customer_id="cust-123")
record_lead(vehicle_id="VH-001", action="availability_check", customer_id="cust-123")

# 2) Prioritize follow-up
get_hot_leads(limit=10)

# 3) Close the loop when sold
record_sale(
    vehicle_id="VH-001",
    sold_price=28995,
    sold_at="2026-02-25T18:30:00+00:00",
    source_channel="organic"
)

# 4) Measure conversion
await get_funnel_metrics(days=30, breakdown_by="source_channel")
```

## Under the hood (quick)
- FastMCP server with 40+ tools
- CIP scaffolds for structured reasoning + response guardrails
- SQLite (WAL mode) for inventory, lead profiles/events, and sales outcomes
- VehicleStore protocol so storage can be swapped later without rewriting tool logic

## Project structure

```text
auto_mcp/
├── server.py                  # MCP tool registration + wrappers
├── config.py                  # Domain config + guardrails
├── data/
│   ├── inventory.py           # Public data facade
│   ├── store.py               # SQLite schema + analytics logic
│   └── seed.py                # Demo vehicles
├── tools/
│   ├── search/details/...     # Buyer-facing tools
│   ├── dealer_intelligence.py # Hot leads, aging, pricing, funnel metrics
│   ├── sales.py               # record_sale
│   └── ingestion.py           # CRUD + import
└── scaffolds/                 # Reasoning scaffolds per tool family
```

## Development

```bash
# Lint
uv run ruff check auto_mcp tests

# Tests
uv run pytest tests -q
```

## License
AutoCIP is licensed under Business Source License 1.1.

See:
- [LICENSE](LICENSE)
- [LICENSE-APACHE](LICENSE-APACHE)
- [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md)
- [TRADEMARKS.md](TRADEMARKS.md)

Licensing contact: `licensing@manticthink.com`
