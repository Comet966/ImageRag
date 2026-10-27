"""Offline regression tests for cache, index integrity and retrieval boundaries."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.core import SearchService, ServiceError, normalize


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = SearchService(self.root)
        self.photos = []
        for position in range(2):
            filename = f"{position}.jpg"
            content = f"synthetic fixture {position}".encode()
            (self.root / filename).write_bytes(content)
            self.photos.append({
                "id": str(position), "path": filename, "sha256": hashlib.sha256(content).hexdigest(),
                # Intentionally misleading labels: retrieval must use only vectors.
                "title": "猫" if position else "卡车", "category": str(position),
            })
        self.write_manifest()

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def write_manifest(self):
        (self.root / "manifest.json").write_text(json.dumps({"photos": self.photos}))

    def populate(self):
        with patch.object(self.service, "embed", return_value=[[1.0, 0.0], [0.0, 1.0]]) as embed, patch("backend.core.image_input", return_value="data:image/jpeg;base64,fixture"):
            self.service.index()
            self.assertEqual(embed.call_args.args[0], [{"image": "data:image/jpeg;base64,fixture"}] * 2)

    def test_search_uses_vectors_not_titles_and_normalizes(self):
        self.populate()
        with patch.object(self.service, "query_vectors", return_value=[[1.0, 0.0]]):
            result = self.service.search("猫")
        self.assertEqual(result["results"][0]["id"], "0")
        self.assertEqual(result["results"][0]["score"], 1)
        self.assertEqual(normalize([3, 4]), [.6, .8])

    def test_index_resume_makes_no_duplicate_api_call(self):
        self.populate()
        with patch.object(self.service, "embed") as embed:
            self.assertEqual(self.service.index()["indexed"], 2)
            embed.assert_not_called()

    def test_file_change_requires_reindex_and_checks_hash(self):
        self.populate()
        self.photos[0]["sha256"] = "changed"
        self.write_manifest()
        self.assertEqual(self.service.status()["indexed"], 1)
        with self.assertRaises(ServiceError):
            self.service.index()

    def test_query_cache_and_model_config_isolation(self):
        with patch.object(self.service, "embed", return_value=[[1.0, 0.0]]) as embed:
            self.service.query_vectors(["中文", "中文"])
            self.service.query_vectors(["中文"])
            self.assertEqual(embed.call_count, 1)
        self.populate()
        self.service.model_key = "different-model"
        self.assertEqual(self.service.status()["indexed"], 0)

    def test_media_filter_limits_vector_candidates(self):
        self.photos[0]["media_type"] = "photo"
        self.photos[1]["media_type"] = "screenshot"
        self.write_manifest()
        self.populate()
        with patch.object(self.service, "query_vectors", return_value=[[1.0, 0.0]]):
            result = self.service.search("任意描述", media_type="screenshot")
        self.assertEqual(result["searched"], 1)
        self.assertEqual(result["results"][0]["id"], "1")
        with self.assertRaises(ServiceError):
            self.service.search("任意描述", media_type="invalid")

    def test_bad_queries_empty_index_and_dimensions(self):
        for query in ("", "  ", "猫" * 1001):
            with self.assertRaises(ServiceError):
                self.service.search(query)
        with self.assertRaises(ServiceError):
            self.service.search("猫")
        self.populate()
        with patch.object(self.service, "query_vectors", return_value=[[1.0, 0.0, 0.0]]):
            with self.assertRaises(ServiceError):
                self.service.search("猫")
        for vector in ([], [0, 0], [float("nan")], [float("inf")]):
            with self.assertRaises(ServiceError):
                normalize(vector)


if __name__ == "__main__":
    unittest.main()
