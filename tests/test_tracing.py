from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from tracing import create_trace, flush


class TestCreateTrace:
    def test_no_env_vars_returns_none(self):
        with patch("tracing._langfuse", None):
            with patch.dict(os.environ, {}, clear=True):
                result = create_trace("test")
                assert result is None

    def test_missing_secret_key_returns_none(self):
        with patch("tracing._langfuse", None):
            with patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "pk"}):
                result = create_trace("test")
                assert result is None

    def test_missing_public_key_returns_none(self):
        with patch("tracing._langfuse", None):
            with patch.dict(os.environ, {"LANGFUSE_SECRET_KEY": "sk"}):
                result = create_trace("test")
                assert result is None

    def test_env_vars_set_creates_trace(self):
        with patch("tracing._langfuse", None):
            mock_langfuse = MagicMock()
            mock_trace = MagicMock()
            mock_langfuse.trace.return_value = mock_trace

            with patch.dict(
                os.environ,
                {
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                    "LANGFUSE_HOST": "https://custom.langfuse.com",
                },
            ):
                with patch(
                    "langfuse.Langfuse", return_value=mock_langfuse
                ) as mock_lf_cls:
                    result = create_trace("test-trace", user_id="user-1")

                    mock_lf_cls.assert_called_once_with(
                        secret_key="sk-test",
                        public_key="pk-test",
                        host="https://custom.langfuse.com",
                    )
                    mock_langfuse.trace.assert_called_once_with(
                        name="test-trace", user_id="user-1"
                    )
                    assert result is mock_trace

    def test_default_host(self):
        with patch("tracing._langfuse", None):
            with patch.dict(
                os.environ,
                {
                    "LANGFUSE_SECRET_KEY": "sk-test",
                    "LANGFUSE_PUBLIC_KEY": "pk-test",
                },
            ):
                with patch("langfuse.Langfuse") as mock_lf_cls:
                    create_trace("test")

                    mock_lf_cls.assert_called_once_with(
                        secret_key="sk-test",
                        public_key="pk-test",
                        host="https://cloud.langfuse.com",
                    )


class TestFlush:
    def test_no_client_noop(self):
        with patch("tracing._langfuse", None):
            flush()

    def test_flush_called_on_client(self):
        mock_langfuse = MagicMock()
        with patch("tracing._langfuse", mock_langfuse):
            flush()
            mock_langfuse.flush.assert_called_once()
