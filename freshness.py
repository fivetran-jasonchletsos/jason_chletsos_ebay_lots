"""Content-addressed freshness for the refresh pipeline.

Replaces hand-curated "run X after Y" with a make-style staleness check:
each agent declares its INPUTS (files it reads) and OUTPUTS (files it
writes). The orchestrator skips an agent if all its OUTPUTS exist and are
newer than every INPUT.

Two ways agents declare their I/O:
  1. Module-level constants — set `INPUTS = ['inventory.csv', ...]` and
     `OUTPUTS = ['output/inventory_plan.json', 'docs/inventory.html']` at
     module scope. Cheap, works for static dependencies.
  2. Override via this module's registry — `register_io(script_name,
     inputs=[...], outputs=[...])`. Used when a generator's inputs aren't
     literal in the agent file (e.g., dependencies on linkage_db).

Paths are relative to the repo root and resolved against paths.REPO.
"""
from __future__ import annotations
import importlib
import importlib.util
import os
from pathlib import Path

import paths

# Fallback registry: maps script basename to (inputs, outputs). Used for
# agents that don't declare their own metadata. Populated below for the
# generators refresh_pipeline cares about.
_REGISTRY: dict[str, tuple[list[str], list[str]]] = {}


def register_io(script_name: str, *, inputs: list[str], outputs: list[str]) -> None:
    """Register inputs/outputs for a script that doesn't declare its own."""
    _REGISTRY[script_name] = (list(inputs), list(outputs))


def _module_io(script_name: str) -> tuple[list[str], list[str]] | None:
    """Try to import the script as a module and read its INPUTS / OUTPUTS
    constants. Returns None if import fails or constants are missing."""
    script_path = paths.REPO / script_name
    if not script_path.is_file():
        return None
    mod_name = script_path.stem
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(script_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Import side-effects: most generator scripts just define functions
        # and call main() inside `if __name__ == '__main__':`. Safe to import.
        spec.loader.exec_module(mod)
    except Exception:
        return None
    inputs  = getattr(mod, "INPUTS", None)
    outputs = getattr(mod, "OUTPUTS", None)
    if inputs is None or outputs is None:
        return None
    return list(inputs), list(outputs)


def get_io(script_name: str) -> tuple[list[str], list[str]] | None:
    """Look up I/O for a script. Tries module-level constants first, then
    the registry. Returns None when neither is available — caller should
    treat that as 'always run' (no staleness opinion)."""
    via_module = _module_io(script_name)
    if via_module is not None:
        return via_module
    if script_name in _REGISTRY:
        return _REGISTRY[script_name]
    return None


def _mtime(p: Path) -> float:
    """Last-modified time, or 0.0 if missing."""
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def is_stale(script_name: str) -> tuple[bool, str]:
    """Return (stale, reason). Stale=True means the agent should run.
    Reasons help debug: 'no I/O declared', 'missing output X',
    'input Y newer than output Z', etc."""
    io = get_io(script_name)
    if io is None:
        return True, "no I/O declared — always run"
    inputs, outputs = io

    # If ANY output is missing, the agent must run.
    for out_rel in outputs:
        out_p = paths.REPO / out_rel
        if not out_p.exists():
            return True, f"missing output {out_rel}"

    # The youngest output must be newer than the youngest input.
    in_mtimes  = [(in_rel,  _mtime(paths.REPO / in_rel))  for in_rel  in inputs]
    out_mtimes = [(out_rel, _mtime(paths.REPO / out_rel)) for out_rel in outputs]
    if not in_mtimes:
        return False, "no inputs declared, outputs exist — skip"

    newest_input  = max(in_mtimes,  key=lambda x: x[1])
    oldest_output = min(out_mtimes, key=lambda x: x[1])
    if newest_input[1] > oldest_output[1]:
        return True, f"input {newest_input[0]} newer than output {oldest_output[0]}"
    return False, f"all outputs newer than inputs — skip"


# --------------------------------------------------------------------------- #
# Default registry for known generators                                       #
# --------------------------------------------------------------------------- #
#
# These are the agents refresh_pipeline calls. Most of them don't yet have
# INPUTS / OUTPUTS constants in their source; the registry covers them with
# best-known dependencies so the freshness check is useful immediately.
# Future cleanup: move each declaration into its agent file as module-level
# constants and delete the registry entry.

register_io("inventory_agent.py",
            inputs=["inventory.csv", "sportscardspro_prices.json"],
            outputs=["output/inventory_plan.json", "docs/inventory.html"])

register_io("infer_prices_agent.py",
            inputs=["inventory.csv", "output/inventory_plan.json",
                    "sportscardspro_prices.json"],
            outputs=["output/inferred_prices.json"])

register_io("build_collx_vs_ebay.py",
            inputs=["inventory.csv", "output/listings_snapshot.json",
                    "output/inferred_prices.json"],
            outputs=["docs/collx_vs_ebay.html"])

register_io("refresh_snapshot.py",
            inputs=["configuration.json"],
            outputs=["output/listings_snapshot.json"])

register_io("lot_generator_agent.py",
            inputs=["inventory.csv"],
            outputs=["output/lot_generator_plan.json", "docs/lots.html"])

register_io("resale_flips_agent.py",
            inputs=["deal_queries.json"],
            outputs=["output/resale_flips_plan.json", "docs/resale_flips.html"])

register_io("jack_pokemon_agent.py",
            inputs=["output/pokemon_news_plan.json"],
            outputs=["output/jack_pokemon_plan.json", "docs/jack_pokemon.html"])

register_io("buyer_watchlist_agent.py",
            inputs=["buyer_watchlist.json"],
            outputs=["output/buyer_watchlist_plan.json", "docs/collect.html"])

register_io("daily_digest_agent.py",
            inputs=["output/listings_snapshot.json", "output/inventory_plan.json",
                    "output/photo_audit.json", "output/repricing_plan.json",
                    "output/best_offer_plan.json"],
            outputs=["docs/daily.html"])

register_io("sync_docs_json.py",
            inputs=["output/listings_snapshot.json", "docs/_seller.json"],
            outputs=["docs/listings_snapshot.json", "docs/_index_listings.json",
                     "docs/_deals_listings.json"])

# Agents that hit eBay APIs every run regardless of input mtimes — they read
# from a live remote, not from a local file, so they have no meaningful
# "is this stale" answer based on local mtimes. Mark them as ALWAYS RUN by
# not registering them: get_io returns None → is_stale returns True.
#
# photo_audit_agent.py, cassini_score_agent.py, repricing_agent.py,
# best_offer_agent.py, promoted_listings_agent.py, etc. — all left
# unregistered intentionally. They'll always run because their inputs
# (eBay APIs) are not local files.
