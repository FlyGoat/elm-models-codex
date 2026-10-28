# ELM models for Codex

A hosted, coding-only [Codex-native model catalog](https://learn.chatgpt.com/docs/config-file/config-reference)
for the [ELM API](https://elm.edina.ac.uk/api/v1).

**Catalog URL:**

```text
https://flygoat.github.io/elm-models-codex/models.json
```

The updater intersects ELM's live `/models` inventory with the latest stable
[OpenAI Codex release](https://github.com/openai/codex/releases/latest). Exact
model ID matches retain upstream instructions, context limits, reasoning options,
and other metadata. Four locally hosted models have researched, source-backed
metadata in [curated-models.json](curated-models.json). Other eligible ELM text
models receive conservative generic metadata. The catalog does not add models
absent from ELM's inventory.

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
to a known working catalog. The project page also provides the example
configuration and a filtering report:
<https://flygoat.github.io/elm-models-codex/>.

Codex 0.165.0 sends the provider's bearer token when requesting a remote catalog.
GitHub's raw-file endpoint rejects requests carrying an ELM token with HTTP 404;
the project site serves the same JSON through GitHub Pages. No download wrapper
or manually maintained local catalog is required.

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

### Locally hosted models

The [ELM proxy API documentation](https://elm.edina.ac.uk/elm/help/proxy-api) takes
precedence for deployment limits and supported reasoning options. Its help content
was read from ELM's publicly served application bundle because browser navigation
redirected to university sign-in. Publisher model cards and configurations provide
additional context. Sources and dated probe results are preserved in the curated
file and generated metadata report.

| Model | ELM context tokens | Catalog input | Reasoning choices |
| --- | ---: | --- | --- |
| [Qwen 3.5 397B A17B FP8](https://huggingface.co/Qwen/Qwen3.5-397B-A17B-FP8) | 262,144 | Text and images | `none`, `minimal`, `high` |
| [Llama 3.3 70B Instruct](https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct) | 128,000 | Text | None advertised |
| [Mistral Small 4](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603) | 262,144 | Text, temporarily | `none`, `minimal`, `high` |
| [EuroLLM 22B Instruct](https://huggingface.co/utter-project/EuroLLM-22B-Instruct-2512) | 32,768 | Text | None advertised |

Qwen and Mistral default to `high` for coding. ELM documents `minimal` as an alias
for disabling reasoning. OpenAI reasoning summaries remain disabled. Full context
limits have not been load-tested; compaction at 80 percent of each documented limit
is this repository's policy for reserving working space.

Small ELM Responses probes observed native function calls for Qwen and Mistral.
Qwen also identified a red test image. Mistral's image request failed with
`'input_text' is not a valid ChunkTypes`, so image input is disabled in its catalog
entry despite the documented model capability. Llama and EuroLLM returned messages
instead of native function calls in the same probe. This does not prove all tool
use is impossible, but it prevents claiming verified agent operation for them.

An actual Codex 0.165.0 shell-tool check passed for Qwen with hosted web search
disabled. A full Codex request to Mistral failed with `Unknown message role:
developer`, despite its direct API function-calling probe passing. This is an ELM
proxy compatibility issue; the researched metadata does not claim to fix it.

Curated fields are applied after upstream matching, so ELM deployment overrides
survive automatic regeneration. They never bypass the blacklist or add models not
listed by ELM. Newly researched changes belong in `curated-models.json`; the
scheduled job does not scrape model-card prose into configuration automatically.

[catalog-metadata.json](catalog-metadata.json) records the upstream release and
catalog checksum, included models using exact, curated, or generic metadata, and every
excluded model with its reason. No API credentials are published. This catalog is
Codex-specific; it is separate from the ordinary OpenAI-compatible `/models` list.

## Automatic updates

The [GitHub Action](.github/workflows/update-models.yml) runs daily at **06:23 UTC**,
on relevant pushes to `main`, and through **Actions → Update model catalog → Run
workflow**. Pull requests run offline tests only and receive no ELM credentials.
After each successful update, the workflow deploys the current catalog, example
config, filtering report, and a small index page to GitHub Pages. Only those
selected public files are included in the deployment artifact.

Set the repository Actions secret `ELM_API_KEY` to a key allowed to list ELM
models. The workflow uses its built-in `GITHUB_TOKEN` to read the latest stable
Codex release and commit changed `models.json` and `catalog-metadata.json` directly
to `main`. If branch protection prevents bot pushes, allow this automation or
change the publishing step to open a pull request. Pages must use **GitHub
Actions** as its publishing source. The deploy job has `pages: write` and
`id-token: write` permissions for GitHub's deployment action.

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
that full URL. The default URL uses this repository's GitHub Pages project site.
The raw source remains available at
<https://raw.githubusercontent.com/FlyGoat/elm-models-codex/main/models.json> for
anonymous downloads, but is unsuitable for Codex's authenticated catalog fetch.

## Upstream attribution

The generated catalog includes metadata and instruction templates from
[openai/codex](https://github.com/openai/codex), licensed under Apache-2.0.
See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution and modifications.
