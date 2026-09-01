from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pdf2zh.cache import clean_test_db, init_test_db
from pdf2zh.translator import ANTHROPIC_DEFAULT_MODEL, AnthropicTranslator


def _response(status_code: int = 200, payload: dict | None = None) -> mock.Mock:
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    response.raise_for_status = mock.Mock()
    if status_code >= 400:
        import requests

        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    return response


class AnthropicTranslatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = init_test_db()
        self.env_patch = mock.patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=False
        )
        self.env_patch.start()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.temp_directory.cleanup()
        clean_test_db(self.test_db)

    def _glossary_path(self, data: dict) -> str:
        path = self.root / "glossary.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_refuses_to_start_without_an_api_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                AnthropicTranslator("auto", "vi", ignore_cache=True)

    def test_defaults_to_the_fast_model_when_none_is_given(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        self.assertEqual(translator.model_name, ANTHROPIC_DEFAULT_MODEL)

    def test_an_explicit_model_overrides_the_default(self):
        translator = AnthropicTranslator("auto", "vi", "claude-sonnet-5", ignore_cache=True)
        self.assertEqual(translator.model_name, "claude-sonnet-5")

    def test_translates_using_the_configured_model_and_system_prompt(self):
        translator = AnthropicTranslator("auto", "vi", "claude-sonnet-5", ignore_cache=True)
        response = _response(
            payload={"content": [{"type": "text", "text": "Dẫn nhiệt xảy ra"}]}
        )
        with mock.patch.object(translator.session, "post", return_value=response) as post:
            result = translator.do_translate("Conduction occurs")

        self.assertEqual(result, "Dẫn nhiệt xảy ra")
        call = post.call_args
        self.assertEqual(call.kwargs["json"]["model"], "claude-sonnet-5")
        self.assertEqual(call.kwargs["json"]["messages"], [{"role": "user", "content": "Conduction occurs"}])
        self.assertIn("vi", call.kwargs["json"]["system"])
        self.assertEqual(call.kwargs["headers"]["x-api-key"], "sk-ant-test")

    def test_preserves_a_formula_placeholder(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(
            payload={"content": [{"type": "text", "text": "trong đó {v0} đúng"}]}
        )
        with mock.patch.object(translator.session, "post", return_value=response):
            result = translator.do_translate("where {v0} holds")
        self.assertIn("{v0}", result)

    def test_rejects_a_response_that_drops_a_placeholder(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(payload={"content": [{"type": "text", "text": "trong đó đúng"}]})
        with mock.patch.object(translator.session, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "placeholder"):
                translator.do_translate("where {v0} holds")

    def test_rejects_an_empty_translation(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(payload={"content": [{"type": "text", "text": "   "}]})
        with mock.patch.object(translator.session, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                translator.do_translate("Conduction occurs")

    def test_rejects_a_response_with_no_text_blocks(self):
        # An empty "content" list joins to "" rather than raising KeyError, so
        # this is reported the same way as any other empty translation.
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(payload={"content": []})
        with mock.patch.object(translator.session, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                translator.do_translate("Conduction occurs")

    def test_rejects_a_malformed_response_body(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(payload={"unexpected": "shape"})
        with mock.patch.object(translator.session, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "did not contain"):
                translator.do_translate("Conduction occurs")

    def test_reports_an_invalid_key_clearly(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        response = _response(status_code=401)
        with mock.patch.object(translator.session, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid ANTHROPIC_API_KEY"):
                translator.do_translate("Conduction occurs")

    def test_is_registered_under_its_engine_name(self):
        from pdf2zh.translator import ENGINES

        self.assertIs(ENGINES["anthropic"], AnthropicTranslator)

    def test_a_matched_glossary_term_is_added_to_the_system_prompt(self):
        envs = {
            "glossary": self._glossary_path(
                {"conduction": {"vi": "dẫn nhiệt", "domain": "heat-transfer"}}
            )
        }
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True, envs=envs)
        response = _response(payload={"content": [{"type": "text", "text": "Dẫn nhiệt xảy ra"}]})
        with mock.patch.object(translator.session, "post", return_value=response) as post:
            translator.do_translate("Conduction occurs between two bodies")

        system_prompt = post.call_args.kwargs["json"]["system"]
        self.assertIn("MANDATORY TERMINOLOGY", system_prompt)
        self.assertIn("conduction = dẫn nhiệt", system_prompt)

    def test_a_glossary_with_no_hit_leaves_the_system_prompt_unchanged(self):
        envs = {
            "glossary": self._glossary_path(
                {"premise": {"vi": "tiền đề", "domain": "logic"}}
            )
        }
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True, envs=envs)
        response = _response(payload={"content": [{"type": "text", "text": "Dẫn nhiệt xảy ra"}]})
        with mock.patch.object(translator.session, "post", return_value=response) as post:
            translator.do_translate("Conduction occurs between two bodies")

        system_prompt = post.call_args.kwargs["json"]["system"]
        self.assertNotIn("MANDATORY TERMINOLOGY", system_prompt)
        self.assertEqual(system_prompt, translator.system_prompt)

    def test_no_glossary_given_behaves_as_before(self):
        translator = AnthropicTranslator("auto", "vi", ignore_cache=True)
        self.assertEqual(translator.glossary, {})


if __name__ == "__main__":
    unittest.main()
