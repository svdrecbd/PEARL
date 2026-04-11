from __future__ import annotations

import unittest

from pearl.openai_compat_sampler import normalize_openai_base_url


class OpenAICompatSamplerTests(unittest.TestCase):
    def test_normalize_base_url_appends_v1(self) -> None:
        self.assertEqual(normalize_openai_base_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000/v1")

    def test_normalize_base_url_preserves_existing_v1(self) -> None:
        self.assertEqual(normalize_openai_base_url("http://127.0.0.1:8000/v1/"), "http://127.0.0.1:8000/v1")

    def test_normalize_base_url_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            normalize_openai_base_url("   ")
