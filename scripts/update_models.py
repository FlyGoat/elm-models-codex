#!/usr/bin/env python3
"""Build a Codex-native coding catalog from ELM inventory and Codex upstream."""

from __future__ import annotations

import argparse
import copy
import fnmatch
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


def load_rules(document) -> list[str]:
    if not isinstance(document, list) or not document or any(
        not isinstance(pattern, str) or not pattern for pattern in document
    ):
        raise ValueError("Blacklist must be a nonempty list of patterns")
    return document


def generic_model(slug: str) -> dict:
    """Conservative metadata; do not invent context limits or reasoning support."""
    return {
        "slug": slug,
        "display_name": slug,
        "description": "Text model.",
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


def build_catalog(inventory, upstream, blacklist, curated_document=None):
    ids = model_ids(inventory)
    rules = load_rules(blacklist)
    curated_models = (curated_document or {"models": {}})["models"]
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
            (rule for rule in rules if fnmatch.fnmatchcase(slug.lower(), rule.lower())),
            None,
        )
        if rule:
            excluded.append(slug)
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
            model.update(copy.deepcopy(entry))
            model["max_context_window"] = model["context_window"]
            model["auto_compact_token_limit"] = model["context_window"] * 4 // 5
            model["supports_reasoning_summary_parameter"] = False
            curated[slug] = entry
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
    else:
        ref = args.codex_ref or latest_codex_ref()
        upstream, _ = fetch_upstream(ref)
    blacklist = json.loads(args.blacklist.read_text())
    curated = json.loads(args.curated.read_text())
    catalog, metadata = build_catalog(inventory, upstream, blacklist, curated)
    encoded = encode_catalog(catalog)
    write_if_changed(args.output, encoded)
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
