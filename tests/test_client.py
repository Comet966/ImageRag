"""Direct-call behavior, offline isolation and error handling without network I/O."""

import os
import unittest
from unittest.mock import Mock, patch

import requests

from backend.billing import cost_cny
from backend.client import ModelCallError, call_embeddings


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.arguments = {"model": "qwen3-vl-embedding", "base_url": "https://example.com/api/v1",
                          "api_key": "dummy-offline-test-key", "kind": "query"}
        self.env = patch.dict(os.environ, {"IMAGERAG_NO_API": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    @patch("backend.client.requests.post")
    def test_call_sends_directly_without_prompt_or_callback(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"output": {"embeddings": []}, "usage": {"total_tokens": 20}}
        result = call_embeddings([{"text": "咖啡"}], **self.arguments)
        self.assertEqual(result["usage"]["total_tokens"], 20)
        post.assert_called_once()
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(post.call_args.kwargs["json"], {
            "model": "qwen3-vl-embedding", "input": {"contents": [{"text": "咖啡"}]},
            "parameters": {"enable_fusion": False},
        })

    @patch("backend.client.requests.post")
    def test_http_errors_and_timeouts_do_not_retry(self, post):
        post.return_value = Mock(status_code=503, headers={})
        with self.assertRaisesRegex(ModelCallError, "未自动重试"):
            call_embeddings([{"text": "咖啡"}], **self.arguments)
        self.assertEqual(post.call_count, 1)
        post.reset_mock()
        post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(ModelCallError, "未自动重试"):
            call_embeddings([{"text": "咖啡"}], **self.arguments)
        self.assertEqual(post.call_count, 1)

    @patch("backend.client.requests.post")
    def test_offline_mode_never_sends(self, post):
        with patch.dict(os.environ, {"IMAGERAG_NO_API": "1"}):
            with self.assertRaisesRegex(ModelCallError, "离线验收"):
                call_embeddings([{"text": "咖啡"}], **self.arguments)
        post.assert_not_called()

    @patch("backend.client.requests.post")
    def test_invalid_key_or_endpoint_never_sends(self, post):
        arguments = dict(self.arguments, api_key="")
        with self.assertRaises(ModelCallError):
            call_embeddings([{"text": "咖啡"}], **arguments)
        arguments = dict(self.arguments, base_url="http://example.com")
        with self.assertRaises(ModelCallError):
            call_embeddings([{"text": "咖啡"}], **arguments)
        post.assert_not_called()

    def test_usage_pricing_separates_modalities(self):
        self.assertEqual(cost_cny(1000, 1000), .0025)


if __name__ == "__main__":
    unittest.main()
