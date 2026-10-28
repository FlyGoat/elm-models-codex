# ELM models for Codex

Catalog: https://flygoat.github.io/elm-models-codex/models.json

Copy [config.example.toml](config.example.toml) to `$CODEX_HOME/config.toml`,
replace the API key, and remove any existing `model_catalog_json` setting.

The catalog updates daily from ELM's model list and the latest stable Codex
release, then publishes to GitHub Pages. The workflow uses the repository secret
`ELM_API_KEY`.

- [blacklist.json](blacklist.json): excluded model patterns.
- [curated-models.json](curated-models.json): settings for Qwen, Llama, Mistral, and EuroLLM from the [ELM documentation](https://elm.edina.ac.uk/elm/help/proxy-api).
- [scripts/update_models.py](scripts/update_models.py): updater; Python 3.11+, no dependencies.

```sh
export ELM_API_KEY='your-key'
python3 scripts/update_models.py
python3 -m unittest discover -s tests
```

Mistral currently fails on Codex's `developer` messages; image input is disabled
because of a proxy conversion error. Llama and EuroLLM did not produce native tool
calls in initial probes.

Includes metadata from [OpenAI Codex](https://github.com/openai/codex).
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
