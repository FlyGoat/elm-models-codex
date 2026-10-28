# ELM models for Codex

A hosted, coding-only [Codex-native model catalog](https://learn.chatgpt.com/docs/config-file/config-reference)
for the [ELM API](https://elm.edina.ac.uk/api/v1).

**Catalog URL:**

```text
https://raw.githubusercontent.com/FlyGoat/elm-models-codex/main/models.json
```

The updater intersects ELM's live `/models` inventory with the latest stable
[OpenAI Codex release](https://github.com/openai/codex/releases/latest). Exact
model ID matches retain upstream instructions, context limits, reasoning options,
and other metadata. Other eligible ELM text models receive conservative generic
metadata. The catalog does not add models absent from ELM's inventory.

## Configure Codex

Copy [config.example.toml](config.example.toml) to `$CODEX_HOME/config.toml` and
replace `REPLACE_WITH_YOUR_ELM_API_KEY` with your own ELM key. Protect the config
with `chmod 600 "$CODEX_HOME/config.toml"`. The example deliberately supports a
key written directly in the config; do not commit your populated config.

If you prefer an environment variable, replace `experimental_bearer_token` with
`env_key = "ELM_API_KEY"` and export that variable before launching Codex.

Remove any top-level `model_catalog_json` setting so Codex uses the hosted catalog.
Restart existing sessions after changing configuration. The initial catalog and
remote discovery were tested with Codex 0.165.0. Future updates track the latest
stable release; update your CLI alongside the catalog or use a catalog URL pinned
to a known working repository commit.

### ELM web search compatibility

Every generated entry sets `use_responses_lite = false`. This selects the normal
Responses transport and allows hosted web search through ELM's `/responses`
endpoint. ELM does not implement Codex's standalone `/alpha/search` endpoint, so
the example leaves standalone search disabled and enables `web_search = "live"`.

## Filtering and capability limits

[blacklist.json](blacklist.json) contains case-insensitive shell-style patterns
and a reason for each exclusion. Audio, speech, image-generation, embedding,
moderation, search-only, deep-research, internal review, and legacy completion
models are omitted completely. Edit this file to change policy.

General-purpose text models are retained because they can be used for coding;
inclusion is not a coding benchmark or a guarantee of Responses/tool compatibility.
For unknown models, the generator does not invent context limits, reasoning
controls, vision support, or search capabilities. Their defaults are deliberately
conservative. Even models with upstream metadata are not all inference-tested
through ELM.

[catalog-metadata.json](catalog-metadata.json) records the upstream release and
catalog checksum, included models using exact or generic metadata, and every
excluded model with its reason. No API credentials are published. This catalog is
Codex-specific; it is separate from the ordinary OpenAI-compatible `/models` list.

## Automatic updates

The [GitHub Action](.github/workflows/update-models.yml) runs daily at **06:23 UTC**,
on relevant pushes to `main`, and through **Actions → Update model catalog → Run
workflow**. Pull requests run offline tests only and receive no ELM credentials.

Set the repository Actions secret `ELM_API_KEY` to a key allowed to list ELM
models. The workflow uses its built-in `GITHUB_TOKEN` to read the latest stable
Codex release and commit changed `models.json` and `catalog-metadata.json` directly
to `main`. If branch protection prevents bot pushes, allow this automation or
change the publishing step to open a pull request.

The optional manual `codex_ref` input can select a specific upstream release tag
or commit. Without an override, the next scheduled run returns to the latest
stable release. GitHub may delay scheduled runs and disables schedules in public
repositories after prolonged inactivity; check the Actions page if updates stop.

## Run locally

Python 3.11 or newer is sufficient; no third-party packages are needed.

```sh
export ELM_API_KEY='your-elm-key'
python3 scripts/update_models.py
python3 -m unittest discover -s tests -v
```

Use `--codex-ref rust-v0.165.0` to select a release. For an entirely offline replay:

```sh
python3 scripts/update_models.py \
  --elm-models-file /path/to/elm-models-response.json \
  --upstream-catalog-file /path/to/codex-upstream-models.json \
  --codex-ref rust-v0.165.0
```

Generation is deterministic: reordering the ELM inventory does not change output,
and unchanged files are not rewritten. Network failures, invalid input, an empty
filtered inventory, and catalogs exceeding Codex's **1 MiB** remote response limit
fail before replacing generated files. The compact JSON keeps upstream instruction
templates within that limit. To inspect it locally:

```sh
python3 -m json.tool models.json
```

## Hosting elsewhere

Serve `models.json` over HTTPS as `application/json`, accepting query parameters
such as `?client_version=0.165.0`. Set `model_providers.elm.model_catalog_url` to
that full URL. GitHub's raw URL already provides the hosted file without Pages or
an additional deployment.

## Upstream attribution

The generated catalog includes metadata and instruction templates from
[openai/codex](https://github.com/openai/codex), licensed under Apache-2.0.
See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution and modifications.
