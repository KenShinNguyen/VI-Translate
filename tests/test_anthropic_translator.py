from __future__ import annotations

import unittest
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

    def tearDown(self) -> None:
        self.env_patch.stop()
        clean_test_db(self.test_db)

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


if __name__ == "__main__":
    unittest.main()
