# Copyright 2026 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test cases for the keyword planner tools."""

import unittest
from unittest.mock import MagicMock, patch

from fastmcp.exceptions import ToolError
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v25.common.types.keyword_plan_common import (
    KeywordPlanHistoricalMetrics,
    MonthlySearchVolume,
)
from google.ads.googleads.v25.services.types.keyword_plan_idea_service import (
    GenerateKeywordHistoricalMetricsResponse,
    GenerateKeywordHistoricalMetricsResult,
    GenerateKeywordIdeaResponse,
    GenerateKeywordIdeaResult,
)

from ads_mcp.tools import keyword_planner


def _metrics(**overrides):
    fields = {
        "avg_monthly_searches": 1000,
        "competition": "LOW",
        "competition_index": 12,
        "low_top_of_page_bid_micros": 450_000,
        "high_top_of_page_bid_micros": 1_230_000,
        "monthly_search_volumes": [
            MonthlySearchVolume(
                year=2026, month="SEPTEMBER", monthly_searches=880
            )
        ],
    }
    fields.update(overrides)
    return KeywordPlanHistoricalMetrics(**fields)


class TestGenerateKeywordHistoricalMetrics(unittest.TestCase):

    @patch("ads_mcp.utils.get_googleads_service")
    def test_builds_request_and_formats_results(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.generate_keyword_historical_metrics.return_value = (
            GenerateKeywordHistoricalMetricsResponse(
                results=[
                    GenerateKeywordHistoricalMetricsResult(
                        text="teppichsockelleiste",
                        close_variants=["teppich sockelleiste"],
                        keyword_metrics=_metrics(),
                    )
                ]
            )
        )

        result = keyword_planner.generate_keyword_historical_metrics(
            customer_id="342-119-4482",
            keywords=["teppichsockelleiste"],
            login_customer_id="111",
        )

        mock_get_service.assert_called_once_with(
            "KeywordPlanIdeaService", login_customer_id="111"
        )
        mock_service.generate_keyword_historical_metrics.assert_called_once_with(
            request={
                "customer_id": "3421194482",
                "keywords": ["teppichsockelleiste"],
                "language": "languageConstants/1001",
                "geo_target_constants": ["geoTargetConstants/2276"],
                "include_adult_keywords": False,
                "keyword_plan_network": "GOOGLE_SEARCH",
            }
        )
        self.assertEqual(
            result,
            [
                {
                    "text": "teppichsockelleiste",
                    "close_variants": ["teppich sockelleiste"],
                    "avg_monthly_searches": 1000,
                    "competition": "LOW",
                    "competition_index": 12,
                    "low_top_of_page_bid": 0.45,
                    "high_top_of_page_bid": 1.23,
                    "monthly_search_volumes": [
                        {
                            "year": 2026,
                            "month": "SEPTEMBER",
                            "monthly_searches": 880,
                        }
                    ],
                }
            ],
        )

    @patch("ads_mcp.utils.get_googleads_service")
    def test_accepts_resource_names(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        keyword_planner.generate_keyword_historical_metrics(
            customer_id="1",
            keywords=["x"],
            language="languageConstants/1000",
            geo_target_constants=["geoTargetConstants/2840", "2040"],
        )

        request = (
            mock_service.generate_keyword_historical_metrics.call_args.kwargs[
                "request"
            ]
        )
        self.assertEqual(request["language"], "languageConstants/1000")
        self.assertEqual(
            request["geo_target_constants"],
            ["geoTargetConstants/2840", "geoTargetConstants/2040"],
        )

    @patch("ads_mcp.utils.get_googleads_service")
    def test_missing_metrics_are_none(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.generate_keyword_historical_metrics.return_value = (
            GenerateKeywordHistoricalMetricsResponse(
                results=[
                    GenerateKeywordHistoricalMetricsResult(
                        text="obscure",
                        keyword_metrics=KeywordPlanHistoricalMetrics(),
                    )
                ]
            )
        )

        (result,) = keyword_planner.generate_keyword_historical_metrics(
            customer_id="1", keywords=["obscure"]
        )

        self.assertIsNone(result["avg_monthly_searches"])
        self.assertIsNone(result["competition_index"])
        self.assertIsNone(result["low_top_of_page_bid"])
        self.assertIsNone(result["high_top_of_page_bid"])

    def test_rejects_empty_and_oversized_keyword_lists(self):
        with self.assertRaises(ToolError):
            keyword_planner.generate_keyword_historical_metrics(
                customer_id="1", keywords=[]
            )
        with self.assertRaises(ToolError):
            keyword_planner.generate_keyword_historical_metrics(
                customer_id="1", keywords=["k"] * 10_001
            )

    @patch("ads_mcp.utils.get_googleads_service")
    def test_api_error_becomes_tool_error(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        failure = MagicMock()
        failure.errors = [MagicMock(message="explorer access")]
        mock_service.generate_keyword_historical_metrics.side_effect = (
            GoogleAdsException(None, None, failure, "req-1")
        )

        with self.assertRaisesRegex(ToolError, "req-1[\\s\\S]*explorer access"):
            keyword_planner.generate_keyword_historical_metrics(
                customer_id="1", keywords=["x"]
            )


class TestGenerateKeywordIdeas(unittest.TestCase):

    def _service_returning(self, mock_get_service, page):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.generate_keyword_ideas.return_value.pages = iter([page])
        return mock_service

    @patch("ads_mcp.utils.get_googleads_service")
    def test_returns_single_page_with_token(self, mock_get_service):
        mock_service = self._service_returning(
            mock_get_service,
            GenerateKeywordIdeaResponse(
                results=[
                    GenerateKeywordIdeaResult(
                        text="teppich ketteln",
                        keyword_idea_metrics=_metrics(),
                    )
                ],
                total_size=250,
                next_page_token="next",
            ),
        )

        result = keyword_planner.generate_keyword_ideas(
            customer_id="1",
            seed_keywords=["teppich"],
            page_size=1,
            page_token="prev",
        )

        request = mock_service.generate_keyword_ideas.call_args.kwargs[
            "request"
        ]
        self.assertEqual(request["keyword_seed"], {"keywords": ["teppich"]})
        self.assertEqual(request["page_size"], 1)
        self.assertEqual(request["page_token"], "prev")
        self.assertEqual(result["total_size"], 250)
        self.assertEqual(result["next_page_token"], "next")
        self.assertEqual(result["ideas"][0]["text"], "teppich ketteln")
        self.assertEqual(result["ideas"][0]["avg_monthly_searches"], 1000)

    @patch("ads_mcp.utils.get_googleads_service")
    def test_last_page_has_no_token(self, mock_get_service):
        self._service_returning(
            mock_get_service, GenerateKeywordIdeaResponse(total_size=0)
        )

        result = keyword_planner.generate_keyword_ideas(
            customer_id="1", seed_keywords=["x"]
        )

        self.assertIsNone(result["next_page_token"])
        self.assertEqual(result["ideas"], [])

    @patch("ads_mcp.utils.get_googleads_service")
    def test_seed_selection(self, mock_get_service):
        cases = [
            (
                {"page_url": "https://example.com"},
                "url_seed",
                {"url": "https://example.com"},
            ),
            (
                {"seed_keywords": ["a"], "page_url": "https://example.com"},
                "keyword_and_url_seed",
                {"url": "https://example.com", "keywords": ["a"]},
            ),
        ]
        for kwargs, seed_field, expected in cases:
            with self.subTest(seed_field=seed_field):
                mock_service = self._service_returning(
                    mock_get_service, GenerateKeywordIdeaResponse()
                )
                keyword_planner.generate_keyword_ideas(
                    customer_id="1", **kwargs
                )
                request = mock_service.generate_keyword_ideas.call_args.kwargs[
                    "request"
                ]
                self.assertEqual(request[seed_field], expected)
                self.assertNotIn("page_token", request)

    def test_rejects_invalid_arguments(self):
        invalid = [
            {},
            {"seed_keywords": ["k"] * 21},
            {"seed_keywords": ["k"], "page_size": 0},
            {"seed_keywords": ["k"], "page_size": 10_001},
        ]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ToolError):
                    keyword_planner.generate_keyword_ideas(
                        customer_id="1", **kwargs
                    )


if __name__ == "__main__":
    unittest.main()
