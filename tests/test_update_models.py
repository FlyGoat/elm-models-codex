import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_models", ROOT / "scripts/update_models.py")
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def inventory(*ids):
    return {"data": [{"id": model_id} for model_id in ids]}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.blacklist = json.loads((ROOT / "blacklist.json").read_text())
        self.native = updater.generic_model("gpt-6.1-sol")
        self.native.update({
            "context_window": 272000,
            "use_responses_lite": True,
            "future_upstream_field": {"preserve": True},
        })
        self.upstream = {"models": [self.native, updater.generic_model("not-in-elm")]}

    def build(self, *ids):
        return updater.build_catalog(inventory(*ids), self.upstream, self.blacklist)

    def test_actual_blacklist_excludes_specialists_and_keeps_text_models(self):
        specialists = [
            "gpt-4o-audio-preview", "gpt-realtime-mini", "gpt-transcribe",
            "whisper-1", "tts-1-hd", "text-embedding-3-small",
            "Snowflake/snowflake-arctic-embed-l-v2.0", "omni-moderation-latest",
            "nemotron_moderator", "meta-llama/Llama-Guard-3-8B", "gpt-image-2",
            "dall-e-3", "gpt-4o-search-preview", "o4-mini-deep-research",
            "codex-auto-review", "gpt-3.5-turbo-instruct", "text-davinci-003",
        ]
        coding = [
            "gpt-6.1-sol", "gpt-5-mini", "gpt-4o", "o3",
            "Qwen/Qwen3.5-397B-A17B-FP8", "meta-llama/Llama-3.3-70B-Instruct",
            "mistralai/Mistral-Small-4-119B-2603", "utter-project/EuroLLM-22B-Instruct-2512",
        ]
        catalog, report = self.build(*(specialists + coding))
        self.assertEqual({model["slug"] for model in catalog["models"]}, set(coding))
        self.assertEqual({item["id"] for item in report["excluded"]}, set(specialists))
        self.assertEqual(report["elm_model_count"], len(specialists + coding))

    def test_upstream_metadata_preserved_except_required_elm_override(self):
        before = copy.deepcopy(self.upstream)
        catalog, report = self.build("gpt-6.1-sol")
        expected = copy.deepcopy(self.native)
        expected["use_responses_lite"] = False
        self.assertEqual(catalog["models"], [expected])
        self.assertEqual(self.upstream, before)
        self.assertEqual(report["upstream_metadata"], ["gpt-6.1-sol"])

    def test_unknown_model_gets_no_invented_limits_or_reasoning_controls(self):
        catalog, report = self.build("future-coding-model")
        model = catalog["models"][0]
        self.assertIsNone(model["context_window"])
        self.assertIsNone(model["max_context_window"])
        self.assertFalse(model["supports_reasoning_summary_parameter"])
        self.assertEqual(model["supported_reasoning_levels"], [])
        self.assertFalse(model["use_responses_lite"])
        self.assertEqual(report["generic_metadata"], ["future-coding-model"])

    def test_inventory_order_does_not_change_artifacts(self):
        first = self.build("gpt-6.1-sol", "gpt-4o", "gpt-audio")
        second = self.build("gpt-audio", "gpt-4o", "gpt-6.1-sol")
        self.assertEqual(first, second)

    def test_case_insensitive_blacklist(self):
        catalog, report = self.build("GPT-AUDIO", "gpt-6.1-sol")
        self.assertEqual(len(catalog["models"]), 1)
        self.assertEqual(report["excluded"][0]["id"], "GPT-AUDIO")

    def test_curated_models_use_elm_limits_and_retain_provenance(self):
        curated = json.loads((ROOT / "curated-models.json").read_text())
        expected = {
            "Qwen/Qwen3.5-397B-A17B-FP8": (262144, ["text", "image"], "high"),
            "meta-llama/Llama-3.3-70B-Instruct": (128000, ["text"], None),
            "mistralai/Mistral-Small-4-119B-2603": (262144, ["text"], "high"),
            "utter-project/EuroLLM-22B-Instruct-2512": (32768, ["text"], None),
        }
        catalog, report = updater.build_catalog(
            inventory(*expected), self.upstream, self.blacklist, curated
        )
        self.assertEqual(report["generic_metadata"], [])
        self.assertEqual(set(report["curated_metadata"]), set(expected))
        for model in catalog["models"]:
            context, modalities, effort = expected[model["slug"]]
            self.assertEqual(model["context_window"], context)
            self.assertEqual(model["max_context_window"], context)
            self.assertEqual(model["auto_compact_token_limit"], context * 80 // 100)
            self.assertEqual(model["input_modalities"], modalities)
            self.assertEqual(model["default_reasoning_level"], effort)
            self.assertFalse(model["use_responses_lite"])
            self.assertFalse(model["supports_reasoning_summary_parameter"])
            self.assertIn("validation", report["curated_metadata"][model["slug"]])
            self.assertNotIn("generic metadata", model["description"])

    def test_curated_entry_overrides_upstream_service_limits_without_mutation(self):
        curated = json.loads((ROOT / "curated-models.json").read_text())
        slug = "meta-llama/Llama-3.3-70B-Instruct"
        upstream = {"models": [updater.generic_model(slug)]}
        upstream["models"][0]["context_window"] = 131072
        upstream["models"][0]["use_responses_lite"] = True
        before = copy.deepcopy(upstream)
        catalog, _ = updater.build_catalog(inventory(slug), upstream, self.blacklist, curated)
        self.assertEqual(catalog["models"][0]["context_window"], 128000)
        self.assertEqual(upstream, before)

    def test_curated_data_cannot_override_identity_or_filtering(self):
        document = json.loads((ROOT / "curated-models.json").read_text())
        entry = copy.deepcopy(next(iter(document["models"].values())))
        with self.assertRaises(ValueError):
            updater.load_curated({"models": {"x": {**entry, "sources": []}}})
        entry["metadata"]["slug"] = "replaced-id"
        with self.assertRaises(ValueError):
            updater.load_curated({"models": {"x": entry}})
        del entry["metadata"]["slug"]
        catalog, report = updater.build_catalog(
            inventory("gpt-audio", "gpt-6.1-sol"), self.upstream, self.blacklist,
            {"models": {"gpt-audio": entry}},
        )
        self.assertEqual([model["slug"] for model in catalog["models"]], ["gpt-6.1-sol"])
        self.assertEqual(report["curated_metadata"], {})

    def test_bad_inputs_and_empty_result_rejected(self):
        invalid = [
            {}, {"data": []}, inventory("duplicate", "duplicate"),
            {"data": [{"id": None}]}, {"data": ["not-an-object"]},
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                updater.build_catalog(data, self.upstream, self.blacklist)
        with self.assertRaises(ValueError):
            self.build("gpt-audio")
        with self.assertRaises(ValueError):
            updater.build_catalog(inventory("gpt-6.1-sol"), {"models": []}, self.blacklist)
        with self.assertRaises(ValueError):
            updater.build_catalog(inventory("gpt-6.1-sol"), self.upstream, {"rules": [{}]})

    def test_http_body_limit_counts_utf8_bytes(self):
        with patch.object(updater, "MAX_CATALOG_BYTES", 100):
            with self.assertRaises(ValueError):
                updater.encode_catalog({"models": [{"description": "猫" * 30}]})

    def test_noop_write_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            updater.write_if_changed(path, b"example")
            previous = path.stat().st_mtime_ns
            updater.write_if_changed(path, b"example")
            self.assertEqual(path.stat().st_mtime_ns, previous)
            updater.write_if_changed(path, b"updated")
            self.assertEqual(path.read_bytes(), b"updated")

    def test_example_uses_hosted_catalog_and_no_real_credential(self):
        config = tomllib.loads((ROOT / "config.example.toml").read_text())
        provider = config["model_providers"]["elm"]
        self.assertEqual(provider["experimental_bearer_token"], "REPLACE_WITH_YOUR_ELM_API_KEY")
        self.assertEqual(provider["model_catalog_url"],
                         "https://flygoat.github.io/elm-models-codex/models.json")
        self.assertNotIn("model_catalog_json", config)
        self.assertEqual(config["web_search"], "live")
        self.assertFalse(provider["supports_standalone_web_search"])
        self.assertFalse(config["features"]["standalone_web_search"])


if __name__ == "__main__":
    unittest.main()
