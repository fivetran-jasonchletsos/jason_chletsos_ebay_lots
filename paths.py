"""Single source of truth for every file path in the repo.

Before: REPO_ROOT, REPO, CACHE_DIR, OUTPUT_DIR, snapshot path, inferred-prices
path were redefined in many files. Touching one didn't propagate. This module
owns them all.

Import pattern:
    from paths import REPO, OUTPUT, SNAPSHOT, INVENTORY_CSV, INFERRED_PRICES
"""
from pathlib import Path

REPO   = Path(__file__).parent.resolve()
OUTPUT = REPO / "output"
DOCS   = REPO / "docs"
STATE  = REPO / "state"

# Source data
INVENTORY_CSV       = REPO / "inventory.csv"
SCP_PRICES_JSON     = REPO / "sportscardspro_prices.json"
SOLD_HISTORY_JSON   = REPO / "sold_history.json"
CONFIG              = REPO / "configuration.json"
BUYER_WATCHLIST     = REPO / "buyer_watchlist.json"
DEAL_QUERIES        = REPO / "deal_queries.json"

# Linkage SQLite database
LINKAGE_DB = STATE / "linkage.db"

# Canonical listings snapshot
SNAPSHOT = OUTPUT / "listings_snapshot.json"

# Multi-source price inference output
INFERRED_PRICES = OUTPUT / "inferred_prices.json"

# Inventory plan (multi-source pricing per card)
INVENTORY_PLAN = OUTPUT / "inventory_plan.json"

# Push history logs
PUSH_BATCH_LOG  = OUTPUT / "push_to_ebay_batch_log.json"
PUSH_SINGLE_LOG = OUTPUT / "push_to_ebay_log.json"

# eBay Trading API endpoint
TRADING_URL = "https://api.ebay.com/ws/api.dll"

# Local image cache for printable PDFs
PDF_IMG_CACHE = REPO / ".cache" / "pdf_images"
