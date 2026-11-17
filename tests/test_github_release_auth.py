"""Regression tests for authenticated GitHub release metadata requests."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import data_sources as ds


class Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def json(self):
        return {"assets": [{"name": "yearly_2025.zip"}]}


class TestGithubReleaseAuthentication(unittest.TestCase):
    def test_extra_auth_header_is_request_scoped(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = Response()
        ds.fetch_json_reliably(
            session, ds.RELEASE_API, attempts=1,
            headers={"Authorization": "Bearer test-token"},
        )
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["headers"]["Connection"], "close")
        # Session-wide headers must not receive the token: exchange and
        # release asset download requests use the same session instance.
        self.assertNotIn("Authorization", session.headers)

    def test_download_archives_uses_actions_token_for_metadata(self):
        fake_session = Mock()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"GITHUB_TOKEN": "test-actions-token"}), \
             patch.object(ds, "session", return_value=fake_session), \
             patch.object(ds, "fetch_json_reliably", side_effect=RuntimeError("stop-after-metadata")) as fetch:
            with self.assertRaisesRegex(RuntimeError, "stop-after-metadata"):
                ds.download_archives(ds.History(), Path(tmp), "2026-11-17", 2025)
        headers = fetch.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-actions-token")
        self.assertEqual(fetch.call_args.args[1], ds.RELEASE_API)

    def test_no_token_uses_public_release_headers_only(self):
        fake_session = Mock()
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"GITHUB_TOKEN": ""}), \
             patch.object(ds, "session", return_value=fake_session), \
             patch.object(ds, "fetch_json_reliably", side_effect=RuntimeError("stop-after-metadata")) as fetch:
            with self.assertRaisesRegex(RuntimeError, "stop-after-metadata"):
                ds.download_archives(ds.History(), Path(tmp), "2026-11-17", 2025)
        self.assertNotIn("Authorization", fetch.call_args.kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
