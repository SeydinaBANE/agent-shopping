from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch


from handler import _is_fast_path


class TestIsFastPath:
    def test_bonjour_is_fast(self) -> None:
        assert _is_fast_path("Bonjour") is True

    def test_merci_is_fast(self) -> None:
        assert _is_fast_path("merci") is True

    def test_complex_query_not_fast(self) -> None:
        assert _is_fast_path("Je cherche une robe rouge") is False

    def test_case_insensitive(self) -> None:
        assert _is_fast_path("BONJOUR") is True

    def test_oui_is_fast(self) -> None:
        assert _is_fast_path("oui") is True


class TestLambdaHandler:
    @patch("handler.bedrock_runtime")
    @patch("handler.ssm")
    def test_health_check_response(
        self,
        mock_ssm: MagicMock,
        mock_bedrock: MagicMock,
    ) -> None:
        from handler import lambda_handler

        event = {
            "body": json.dumps(
                {
                    "message": "Bonjour",
                    "history": [],
                    "tenant_id": "test",
                }
            ),
        }
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 5000

        mock_ssm.get_parameters_by_path.return_value = {"Parameters": []}
        mock_bedrock.invoke_model.return_value = {
            "body": MagicMock(
                read=MagicMock(
                    return_value=json.dumps(
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Bonjour ! Comment puis-je vous aider ?",
                                }
                            ],
                        }
                    )
                )
            )
        }

        response = lambda_handler(event, context)
        assert response["statusCode"] == 200

        body: dict[str, Any] = json.loads(response["body"])
        assert "response" in body

    def test_missing_message(self) -> None:
        from handler import lambda_handler

        event = {"body": json.dumps({})}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response["statusCode"] == 400

    def test_invalid_json(self) -> None:
        from handler import lambda_handler

        event = {"body": "not json"}
        context = MagicMock()

        response = lambda_handler(event, context)
        assert response["statusCode"] == 400
