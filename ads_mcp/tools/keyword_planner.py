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

"""Tools for keyword research via KeywordPlanIdeaService.

Keyword ideas and search volumes are not queryable through GAQL; they are
served by dedicated KeywordPlanIdeaService RPCs.
"""

from typing import Any, Dict, List
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from google.ads.googleads.errors import GoogleAdsException
from mcp.types import ToolAnnotations

import ads_mcp.utils as utils

keywords_mcp = FastMCP("keywords")

_MAX_HISTORICAL_KEYWORDS = 10_000
_MAX_SEED_KEYWORDS = 20
_MAX_PAGE_SIZE = 10_000


def _targeting(
    language: str | None, geo_target_constants: List[str] | None
) -> Dict[str, Any]:
    """Returns the language and geo request fields; omitted ones mean all."""
    targeting: Dict[str, Any] = {}
    if language:
        targeting["language"] = (
            f"languageConstants/{str(language).removeprefix('languageConstants/')}"
        )
    if geo_target_constants:
        targeting["geo_target_constants"] = [
            f"geoTargetConstants/{str(geo).removeprefix('geoTargetConstants/')}"
            for geo in geo_target_constants
        ]
    return targeting


def _micros_to_units(metrics, field: str) -> float | None:
    return getattr(metrics, field) / 1_000_000 if field in metrics else None


def _format_metrics(metrics) -> Dict[str, Any]:
    return {
        "avg_monthly_searches": (
            metrics.avg_monthly_searches
            if "avg_monthly_searches" in metrics
            else None
        ),
        "competition": utils.format_output_value(metrics.competition),
        "competition_index": (
            metrics.competition_index
            if "competition_index" in metrics
            else None
        ),
        "low_top_of_page_bid": _micros_to_units(
            metrics, "low_top_of_page_bid_micros"
        ),
        "high_top_of_page_bid": _micros_to_units(
            metrics, "high_top_of_page_bid_micros"
        ),
        "monthly_search_volumes": [
            {
                "year": volume.year,
                "month": utils.format_output_value(volume.month),
                "monthly_searches": volume.monthly_searches,
            }
            for volume in metrics.monthly_search_volumes
        ],
    }


def _raise_tool_error(ex: GoogleAdsException):
    error_msgs = [
        f"Google Ads API Error: {error.message}" for error in ex.failure.errors
    ]
    raise ToolError(f"Request ID: {ex.request_id}\n" + "\n".join(error_msgs))


@keywords_mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def generate_keyword_historical_metrics(
    customer_id: str | int,
    keywords: List[str],
    language: str | None = None,
    geo_target_constants: List[str] | None = None,
    include_adult_keywords: bool = False,
    login_customer_id: str | int | None = None,
) -> List[Dict[str, Any]]:
    """Returns historical search volume, competition and bid metrics for the given keywords on Google Search.

    Use this to get search volumes for a known list of keywords. Use
    `generate_keyword_ideas` to discover new keywords instead.

    Accounts without active ad spend get bucketed volumes (e.g. 1000 or 10000)
    rather than exact figures; report them as approximate. Bids are in the
    account's currency.

    Args:
        customer_id: The id of the customer, digits only.
        keywords: Up to 10,000 keywords.
        language: Language constant ID or resource name, e.g. 1000 (English). All languages if omitted.
        geo_target_constants: Geo target constant IDs or resource names, e.g. 2840 (United States). All locations if omitted.
        include_adult_keywords: Whether to include adult keywords.
        login_customer_id: Optional manager customer ID to use as the login-customer-id header.

    Returns:
        One entry per keyword with its metrics and close_variants: other
        keywords whose metrics were merged into it.
    """
    if not keywords:
        raise ToolError("keywords must not be empty.")
    if len(keywords) > _MAX_HISTORICAL_KEYWORDS:
        raise ToolError(
            f"At most {_MAX_HISTORICAL_KEYWORDS} keywords are allowed per request."
        )

    service = utils.get_googleads_service(
        "KeywordPlanIdeaService", login_customer_id=login_customer_id
    )
    try:
        response = service.generate_keyword_historical_metrics(
            request={
                "customer_id": utils.clean_customer_id(customer_id),
                "keywords": keywords,
                **_targeting(language, geo_target_constants),
                "include_adult_keywords": include_adult_keywords,
                "keyword_plan_network": "GOOGLE_SEARCH",
            }
        )
    except GoogleAdsException as ex:
        _raise_tool_error(ex)

    return [
        {
            "text": result.text,
            "close_variants": list(result.close_variants),
            **_format_metrics(result.keyword_metrics),
        }
        for result in response.results
    ]


@keywords_mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def generate_keyword_ideas(
    customer_id: str | int,
    seed_keywords: List[str] | None = None,
    page_url: str | None = None,
    language: str | None = None,
    geo_target_constants: List[str] | None = None,
    include_adult_keywords: bool = False,
    page_size: int = 100,
    page_token: str | None = None,
    login_customer_id: str | int | None = None,
) -> Dict[str, Any]:
    """Generates new keyword ideas on Google Search from seed keywords, a page URL, or both.

    Each idea comes with search volume, competition and bid metrics. Accounts
    without active ad spend get bucketed volumes (e.g. 1000 or 10000) rather
    than exact figures; report them as approximate. Bids are in the account's
    currency.

    Args:
        customer_id: The id of the customer, digits only.
        seed_keywords: Up to 20 seed keywords.
        page_url: A page URL to seed ideas from.
        language: Language constant ID or resource name, e.g. 1000 (English). All languages if omitted.
        geo_target_constants: Geo target constant IDs or resource names, e.g. 2840 (United States). All locations if omitted.
        include_adult_keywords: Whether to include adult keywords.
        page_size: Number of ideas per page, at most 10,000.
        page_token: next_page_token from a previous call, to fetch the next page.
        login_customer_id: Optional manager customer ID to use as the login-customer-id header.

    Returns:
        ideas, total_size, and next_page_token (null on the last page).
    """
    if not seed_keywords and not page_url:
        raise ToolError("Provide seed_keywords, page_url, or both.")
    if seed_keywords and len(seed_keywords) > _MAX_SEED_KEYWORDS:
        raise ToolError(
            f"At most {_MAX_SEED_KEYWORDS} seed keywords are allowed per request."
        )
    if not 1 <= page_size <= _MAX_PAGE_SIZE:
        raise ToolError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}.")

    request: Dict[str, Any] = {
        "customer_id": utils.clean_customer_id(customer_id),
        **_targeting(language, geo_target_constants),
        "include_adult_keywords": include_adult_keywords,
        "keyword_plan_network": "GOOGLE_SEARCH",
        "page_size": page_size,
    }
    if page_token:
        request["page_token"] = page_token
    if seed_keywords and page_url:
        request["keyword_and_url_seed"] = {
            "url": page_url,
            "keywords": seed_keywords,
        }
    elif seed_keywords:
        request["keyword_seed"] = {"keywords": seed_keywords}
    else:
        request["url_seed"] = {"url": page_url}

    service = utils.get_googleads_service(
        "KeywordPlanIdeaService", login_customer_id=login_customer_id
    )
    try:
        # The pager fetches further pages lazily; take only the requested one.
        page = next(iter(service.generate_keyword_ideas(request=request).pages))
    except GoogleAdsException as ex:
        _raise_tool_error(ex)

    return {
        "ideas": [
            {
                "text": result.text,
                **_format_metrics(result.keyword_idea_metrics),
            }
            for result in page.results
        ],
        "total_size": page.total_size,
        "next_page_token": page.next_page_token or None,
    }
