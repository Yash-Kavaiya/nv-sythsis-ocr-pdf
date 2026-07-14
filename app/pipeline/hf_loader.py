"""Load seed rows from a HuggingFace dataset via the datasets-server API
(no heavyweight `datasets` dependency), plus the bundled sample corpus."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

DATASETS_SERVER = "https://datasets-server.huggingface.co"
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_seed.json"


def load_sample_seed() -> list[dict[str, Any]]:
    # Degrade to an empty seed rather than crashing if the corpus is missing;
    # the Data Designer can still work from the prompt alone.
    if not SAMPLE_PATH.exists():
        return []
    return json.loads(SAMPLE_PATH.read_text())


def load_hf_rows(
    dataset: str,
    config: str | None = None,
    split: str = "train",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch up to `limit` rows. Auto-discovers the default config when omitted."""
    with httpx.Client(timeout=30) as client:
        if not config:
            r = client.get(f"{DATASETS_SERVER}/splits", params={"dataset": dataset})
            r.raise_for_status()
            splits = r.json().get("splits", [])
            if not splits:
                raise ValueError(f"No splits found for dataset {dataset!r}")
            wanted = [s for s in splits if s.get("split") == split] or splits
            config = wanted[0]["config"]
            split = wanted[0]["split"]
        r = client.get(
            f"{DATASETS_SERVER}/rows",
            params={"dataset": dataset, "config": config, "split": split,
                    "offset": 0, "length": min(limit, 100)},
        )
        r.raise_for_status()
        rows = r.json().get("rows", [])
    out = []
    for item in rows:
        row = item.get("row", {})
        # Drop non-serializable / binary-ish columns (images come as URL dicts).
        clean = {k: v for k, v in row.items() if isinstance(v, (str, int, float, bool, list, dict))}
        out.append(clean)
    return out
