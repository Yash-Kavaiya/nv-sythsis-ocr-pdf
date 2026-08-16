"""Web Retrieval Agent — finds real-world document examples from the web
based on the user's prompt. Uses Perplexity (via OpenRouter) for grounded
search with citations, with Google SERP as fallback."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

# Perplexity via OpenRouter
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Google SERP API (optional fallback)
SERP_API_KEY = os.environ.get("SERP_API_KEY", "")
SERP_BASE_URL = "https://serpapi.com/search"


@dataclass
class RetrievedExample:
    """A real-world document example found on the web."""
    source_url: str
    title: str
    snippet: str
    doc_type: str
    raw_data: dict[str, Any]
    relevance_score: float = 0.0


class WebRetriever:
    """Retrieves real-world document examples from the web."""

    def __init__(
        self,
        openrouter_key: Optional[str] = None,
        serp_key: Optional[str] = None,
    ):
        self.openrouter_key = openrouter_key or OPENROUTER_API_KEY
        self.serp_key = serp_key or SERP_API_KEY

    def retrieve(
        self,
        prompt: str,
        doc_type: str,
        max_examples: int = 10,
    ) -> list[RetrievedExample]:
        """Retrieve real-world examples for the given prompt and document type."""
        examples = []

        # Try Perplexity first (best for grounded, cited results)
        if self.openrouter_key:
            try:
                examples = self._retrieve_perplexity(prompt, doc_type, max_examples)
            except Exception as e:
                print(f"[WebRetriever] Perplexity failed: {e}")

        # Fallback to Google SERP
        if not examples and self.serp_key:
            try:
                examples = self._retrieve_serp(prompt, doc_type, max_examples)
            except Exception as e:
                print(f"[WebRetriever] SERP failed: {e}")

        # If both fail, return empty list (caller handles fallback)
        return examples[:max_examples]

    def _retrieve_perplexity(
        self,
        prompt: str,
        doc_type: str,
        max_examples: int,
    ) -> list[RetrievedExample]:
        """Use Perplexity via OpenRouter for grounded web search."""
        # Craft a search query that finds real document examples
        search_query = self._build_search_query(prompt, doc_type)

        system_msg = (
            "You are a research agent finding real-world document examples. "
            "Search for actual examples of the specified document type matching the user's prompt. "
            "Return ONLY a JSON array of objects with these keys: "
            "title, url, snippet, doc_type, extracted_fields (object with actual field values from the example). "
            "Focus on real businesses, real invoices/receipts/letters/forms found on the web. "
            "Prioritize examples with visible field values (vendor names, amounts, items, addresses, etc.). "
            "No generic templates - only real instances."
        )

        payload = {
            "model": "perplexity/sonar-pro-search",
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Find {max_examples} real {doc_type} examples for: {search_query}"},
            ],
            "temperature": 0.2,
            "max_tokens": 4000,
        }

        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=60) as client:
            resp = client.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        return self._parse_perplexity_response(content, doc_type)

    def _retrieve_serp(
        self,
        prompt: str,
        doc_type: str,
        max_examples: int,
    ) -> list[RetrievedExample]:
        """Use Google SERP API as fallback."""
        search_query = self._build_search_query(prompt, doc_type)

        params = {
            "api_key": self.serp_key,
            "q": search_query,
            "num": max_examples,
            "engine": "google",
        }

        with httpx.Client(timeout=30) as client:
            resp = client.get(SERP_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        examples = []
        for result in data.get("organic_results", [])[:max_examples]:
            examples.append(RetrievedExample(
                source_url=result.get("link", ""),
                title=result.get("title", ""),
                snippet=result.get("snippet", ""),
                doc_type=doc_type,
                raw_data={"serp_result": result},
                relevance_score=0.5,
            ))
        return examples

    def _build_search_query(self, prompt: str, doc_type: str) -> str:
        """Build an effective search query from prompt + doc_type."""
        # Extract key domain terms from prompt
        domain_terms = self._extract_domain_terms(prompt)

        query_templates = {
            "invoice": [
                f'"{domain_terms}" invoice example site:.com OR site:.org',
                f'"{domain_terms}" tax invoice sample',
                f'real {domain_terms} invoice PDF',
            ],
            "receipt": [
                f'"{domain_terms}" receipt example',
                f'"{domain_terms}" POS receipt sample',
                f'real {domain_terms} store receipt',
            ],
            "letter": [
                f'"{domain_terms}" business letter example',
                f'"{domain_terms}" formal letter sample',
                f'real {domain_terms} correspondence',
            ],
            "form": [
                f'"{domain_terms}" application form example',
                f'"{domain_terms}" registration form sample',
                f'real {domain_terms} form PDF',
            ],
        }

        templates = query_templates.get(doc_type, [f'"{domain_terms}" {doc_type} example'])
        return " OR ".join(templates)

    def _extract_domain_terms(self, prompt: str) -> str:
        """Extract key domain/business terms from the prompt."""
        # Remove common stop words and keep meaningful terms
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "from", "by", "about", "as", "is", "was", "are", "were",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "must", "can",
            "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
            "my", "your", "his", "her", "its", "our", "their", "me", "him", "us", "them",
            "generate", "create", "make", "sample", "data", "document", "documents",
        }

        words = re.findall(r'\b\w+\b', prompt.lower())
        meaningful = [w for w in words if w not in stop_words and len(w) > 2]

        # Take top 5-6 meaningful terms
        return " ".join(meaningful[:6])

    def _parse_perplexity_response(
        self,
        content: str,
        doc_type: str,
    ) -> list[RetrievedExample]:
        """Parse Perplexity's JSON response into RetrievedExample objects."""
        # Extract JSON array from response
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            return []

        try:
            items = json.loads(json_match.group())
        except json.JSONDecodeError:
            return []

        examples = []
        for item in items:
            if not isinstance(item, dict):
                continue
            examples.append(RetrievedExample(
                source_url=item.get("url", ""),
                title=item.get("title", ""),
                snippet=item.get("snippet", ""),
                doc_type=item.get("doc_type", doc_type),
                raw_data=item.get("extracted_fields", {}),
                relevance_score=0.8,
            ))
        return examples


def retrieve_web_examples(
    prompt: str,
    doc_type: str,
    max_examples: int = 10,
) -> list[RetrievedExample]:
    """Convenience function for pipeline integration."""
    retriever = WebRetriever()
    return retriever.retrieve(prompt, doc_type, max_examples)


# ---- Local testing ----
if __name__ == "__main__":
    # Test with a sample prompt
    examples = retrieve_web_examples(
        prompt="software SaaS invoices with subscription billing",
        doc_type="invoice",
        max_examples=3,
    )
    for ex in examples:
        print(f"Title: {ex.title}")
        print(f"URL: {ex.source_url}")
        print(f"Snippet: {ex.snippet[:100]}...")
        print(f"Raw data: {ex.raw_data}")
        print("---")