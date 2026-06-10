import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from web_app import ai_status, calculate_request, chat_completions_url, generate_strategy_script, parse_ai_json, recognize_image_with_ai, windows_ocr_available


class WebAppTests(unittest.TestCase):
    def test_calculate_request(self):
        result = calculate_request(
            {
                "players": 2,
                "position": "BTN",
                "hand": "As Ah",
                "strategy": "balanced",
                "pot": 10,
                "to_call": 2,
                "raise_size": 8,
                "simulations": 100,
                "seed": 7,
            }
        )
        self.assertEqual(result["hand"], ["As", "Ah"])
        self.assertIn(result["recommended_action"], result["action_ev"])
        self.assertIn("THEN", result["strategy_script"])

    def test_calculate_request_rejects_bad_hand(self):
        with self.assertRaises(ValueError):
            calculate_request({"hand": "As"})

    def test_strategy_script_contains_mixed_actions(self):
        script = generate_strategy_script(
            {
                "players": 2,
                "position": "BTN",
                "hand": ["As", "Kh"],
                "board": [],
                "recommended_action": "raise",
                "mixed_strategy": {"fold": 0.1, "call": 0.2, "raise": 0.7},
                "action_ev": {"fold": 0, "call": 1, "raise": 2},
                "equity": 0.55,
                "opponent_range": 0.4,
                "fold_to_raise": 0.42,
                "simulations": 1000,
            }
        )
        self.assertIn("RAISE   70.00%", script)

    def test_parse_ai_json_filters_unknown_fields(self):
        result = parse_ai_json('text {"hand":"As Kh","pot":10,"secret":"no"} text')
        self.assertEqual(result, {"hand": "As Kh", "pot": 10})

    def test_ai_vision_requires_configuration(self):
        with patch("web_app.ENV_FILE", Path("missing-test.env")), patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "AI API"):
                recognize_image_with_ai("data:image/png;base64,aGVsbG8=")

    def test_ai_status_never_returns_key(self):
        with patch.dict(
            os.environ,
            {"AI_API_KEY": "secret", "AI_MODEL": "vision-model"},
            clear=True,
        ):
            status = ai_status()
        self.assertTrue(status["configured"])
        self.assertTrue(status["usable"])
        self.assertNotIn("AI_API_KEY", status)
        self.assertNotIn("secret", str(status))

    def test_ai_status_warns_about_model_whitespace(self):
        with patch("web_app.ENV_FILE", Path("missing-test.env")), patch.dict(
            os.environ,
            {"AI_API_KEY": "secret", "AI_MODEL": "invalid model"},
            clear=True,
        ):
            status = ai_status()
        self.assertTrue(status["configured"])
        self.assertFalse(status["usable"])
        self.assertTrue(status["warnings"])

    def test_chat_completions_url_accepts_base_or_full_endpoint(self):
        with patch.dict(os.environ, {"AI_BASE_URL": "https://example.test/v1"}, clear=True):
            self.assertEqual(chat_completions_url(), "https://example.test/v1/chat/completions")

    def test_windows_ocr_script_is_available(self):
        self.assertTrue(windows_ocr_available())
        with patch.dict(
            os.environ,
            {"AI_BASE_URL": "https://example.test/v1/chat/completions"},
            clear=True,
        ):
            self.assertEqual(chat_completions_url(), "https://example.test/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
