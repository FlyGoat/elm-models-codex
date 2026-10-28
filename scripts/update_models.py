#!/usr/bin/env python3
"""Build a Codex-native coding catalog from ELM inventory and Codex upstream."""

from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ELM_BASE = "https://elm.edina.ac.uk/api/v1"
# Codex's remote catalog client rejects responses larger than 1 MiB.
MAX_CATALOG_BYTES = 1_048_576
UPSTREAM_PATHS = (
    "codex-rs/models-manager/models.json",
    "codex-rs/core/models.json",
)
GENERIC_INSTRUCTIONS = (
    "You are a coding assistant working with the user in a shared workspace. "
    "Follow user instructions and applicable AGENTS.md guidance. Inspect relevant "
    "files before editing, use the available tools, preserve unrelated changes, "
    "and verify your work with appropriate checks. Report outcomes and material "
    "limitations clearly. Do not claim actions or verification you did not perform."
)


def fetch_json(url: str, bearer: str | None = None):
    headers = {"Accept": "application/json", "User-Agent": "elm-models-codex"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if attempt == 2 or (exc.code != 429 and exc.code < 500):
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("Request retries exhausted")


def latest_codex_ref() -> str:
    release = fetch_json(
        "https://api.github.com/repos/openai/codex/releases/latest",
        os.environ.get("GITHUB_TOKEN"),
    )
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("rust-v"):
        raise ValueError("Latest Codex release does not contain a rust-v tag")
    return tag


def fetch_upstream(ref: str):
    encoded_ref = urllib.parse.quote(ref, safe="")
    for path in UPSTREAM_PATHS:
        url = f"https://raw.githubusercontent.com/openai/codex/{encoded_ref}/{path}"
        try:
            return fetch_json(url), url
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    raise ValueError(f"No upstream model catalog found for {ref}")


def model_ids(inventory) -> list[str]:
    entries = inventory.get("data")
    if not isinstance(entries, list) or not entries:
        raise ValueError("ELM inventory must contain a nonempty data array")
    ids = []
    for entry in entries:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("ELM inventory contains an invalid model ID")
        ids.append(model_id)
    if len(ids) != len(set(ids)):
        raise ValueError("ELM inventory contains duplicate model IDs")
    return sorted(ids)


def load_rules(document) -> list[dict]:
    rules = document.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Blacklist must contain a nonempty rules array")
    for rule in rules:
        if not isinstance(rule, dict) or any(
            not isinstance(rule.get(key), str) or not rule[key].strip()
            for key in ("pattern", "reason")
        ):
            raise ValueError("Every blacklist rule requires a pattern and reason")
    return rules


def generic_model(slug: str) -> dict:
    """Conservative metadata; do not invent context limits or reasoning support."""
    return {
        "slug": slug,
        "display_name": slug,
        "description": "ELM-listed text model; generic metadata, tool compatibility unverified.",
        "default_reasoning_level": None,
        "supported_reasoning_levels": [],
        "shell_type": "unified_exec",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 99,
        "model_messages": {"instructions_template": GENERIC_INSTRUCTIONS},
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "supports_reasoning_summary_parameter": False,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "web_search_tool_type": "text",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "supports_image_detail_original": False,
        "context_window": None,
        "max_context_window": None,
        "auto_compact_token_limit": None,
        "experimental_supported_tools": [],
        "input_modalities": ["text"],
        "supports_search_tool": False,
        "supports_experimental_context": False,
        "supports_reasoning_effort_updates": False,
        "node_repl_auto_review_required": False,
        "node_repl_disabled": False,
        "use_responses_lite": False,
    }


def load_curated(document) -> dict:
    models = document.get("models")
    if not isinstance(models, dict):
        raise ValueError("Curated metadata must contain a models object")
    allowed = set(generic_model("placeholder")) - {
        "slug", "visibility", "supported_in_api", "use_responses_lite", "model_messages"
    }
    for slug, entry in models.items():
        if not isinstance(slug, str) or not slug or not isinstance(entry, dict):
            raise ValueError("Invalid curated model entry")
        metadata = entry.get("metadata")
        sources = entry.get("sources")
        if not isinstance(metadata, dict) or not metadata or set(metadata) - allowed:
            raise ValueError(f"Invalid curated metadata fields for {slug}")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(url, str) or not url.startswith("https://") for url in sources
        ):
            raise ValueError(f"Curated model {slug} needs HTTPS source references")
        context = metadata.get("context_window")
        maximum = metadata.get("max_context_window")
        compact = metadata.get("auto_compact_token_limit")
        if any(type(value) is not int or value <= 0 for value in (context, maximum, compact)):
            raise ValueError(f"Curated model {slug} needs positive context/compaction limits")
        if not compact < context <= maximum:
            raise ValueError(f"Inconsistent curated context limits for {slug}")
        if metadata.get("input_modalities") not in (["text"], ["text", "image"]):
            raise ValueError(f"Invalid input modalities for {slug}")
        if not isinstance(entry.get("instructions"), str) or not entry["instructions"].strip():
            raise ValueError(f"Curated model {slug} needs coding instructions")
    return models


def build_catalog(inventory, upstream, blacklist, curated_document=None):
    ids = model_ids(inventory)
    rules = load_rules(blacklist)
    curated_models = load_curated(
        curated_document if curated_document is not None else {"models": {}}
    )
    entries = upstream.get("models")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Upstream catalog must contain a nonempty models array")
    by_slug = {}
    for entry in entries:
        slug = entry.get("slug") if isinstance(entry, dict) else None
        if not isinstance(slug, str) or not slug or slug in by_slug:
            raise ValueError("Upstream catalog has invalid or duplicate slugs")
        by_slug[slug] = entry

    models, excluded, native, generic, curated = [], [], [], [], {}
    for slug in ids:
        rule = next(
            (rule for rule in rules if fnmatch.fnmatchcase(slug.lower(), rule["pattern"].lower())),
            None,
        )
        if rule:
            excluded.append({"id": slug, "reason": rule["reason"], "pattern": rule["pattern"]})
            continue
        if slug in by_slug:
            model = copy.deepcopy(by_slug[slug])
            native.append(slug)
        else:
            model = generic_model(slug)
            if slug not in curated_models:
                generic.append(slug)
        if slug in curated_models:
            entry = curated_models[slug]
            model.update(copy.deepcopy(entry["metadata"]))
            model["model_messages"] = {
                "instructions_template": GENERIC_INSTRUCTIONS + " " + entry["instructions"]
            }
            curated[slug] = copy.deepcopy(entry)
        # ELM implements hosted search in /responses, but not /alpha/search.
        model["use_responses_lite"] = False
        models.append(model)
    if not models:
        raise ValueError("Refusing to publish an empty coding catalog")
    models.sort(key=lambda model: (model.get("priority", 99), model["slug"]))
    return {"models": models}, {
        "elm_model_count": len(ids),
        "included_model_count": len(models),
        "upstream_metadata": native,
        "generic_metadata": generic,
        "curated_metadata": curated,
        "excluded": excluded,
        "compatibility_override": {"use_responses_lite": False},
    }


def encode_catalog(catalog) -> bytes:
    # Compact serialization keeps upstream instruction templates below the HTTP cap.
    encoded = (json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_CATALOG_BYTES:
        raise ValueError(
            f"Catalog is {len(encoded)} bytes; Codex's remote limit is {MAX_CATALOG_BYTES}. "
            "No output was changed. Narrow the model set or reduce instruction templates."
        )
    return encoded


def write_if_changed(path: Path, content: bytes):
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "models.json")
    parser.add_argument("--metadata", type=Path, default=ROOT / "catalog-metadata.json")
    parser.add_argument("--blacklist", type=Path, default=ROOT / "blacklist.json")
    parser.add_argument("--curated", type=Path, default=ROOT / "curated-models.json")
    parser.add_argument("--codex-ref", default=os.environ.get("CODEX_REF") or None)
    parser.add_argument("--elm-models-file", type=Path, help="Use a saved /models response")
    parser.add_argument("--upstream-catalog-file", type=Path, help="Use a saved Codex catalog")
    args = parser.parse_args()
    if args.elm_models_file:
        inventory = json.loads(args.elm_models_file.read_text())
    else:
        key = os.environ.get("ELM_API_KEY")
        if not key:
            parser.error("Set ELM_API_KEY or supply --elm-models-file")
        inventory = fetch_json(f"{ELM_BASE}/models", key)

    if args.upstream_catalog_file:
        upstream = json.loads(args.upstream_catalog_file.read_text())
        ref = args.codex_ref or "local-file"
        source_url = None
    else:
        ref = args.codex_ref or latest_codex_ref()
        upstream, source_url = fetch_upstream(ref)
    blacklist = json.loads(args.blacklist.read_text())
    curated = json.loads(args.curated.read_text())
    catalog, metadata = build_catalog(inventory, upstream, blacklist, curated)
    encoded = encode_catalog(catalog)
    metadata.update({
        "codex_ref": ref,
        "upstream_catalog_url": source_url,
        "upstream_catalog_sha256": hashlib.sha256(
            json.dumps(upstream, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "elm_models_url": f"{ELM_BASE}/models",
        "catalog_bytes": len(encoded),
        "curated_reviewed_at": curated.get("reviewed_at"),
    })
    # Finish all fetching, validation, and serialization before changing artifacts.
    metadata_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode()
    write_if_changed(args.output, encoded)
    write_if_changed(args.metadata, metadata_bytes)
    print(
        f"{ref}: {metadata['included_model_count']}/{metadata['elm_model_count']} models; "
        f"{len(metadata['excluded'])} blacklisted; {len(metadata['curated_metadata'])} curated; "
        f"{len(metadata['generic_metadata'])} generic; "
        f"{len(encoded)} bytes"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as exc:
        # Do not print request headers or response bodies containing credentials.
        print(f"Catalog update failed: {exc}", file=sys.stderr)
        sys.exit(1)
