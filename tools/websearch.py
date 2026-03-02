"""Web search tool using DuckDuckGo (no API key required)."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from tools.base import Tool

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


class WebSearchSchema(BaseModel):
    query: str = Field(..., description="The search query to look up on the web")
    max_results: int = Field(5, description="Maximum number of results to return (1-10)")


class WebSearchTool(Tool):
    """
    Search the web using DuckDuckGo.

    Use this tool when you need:
    - Current information (news, recent events)
    - Documentation or API references
    - Solutions to programming problems
    - Package/library information
    - Any information you're unsure about
    """

    name = "websearch"
    description = """Search the web for current information. Use when you need:
- Up-to-date information (news, releases, docs)
- Programming solutions or best practices
- Package/library documentation
- Any factual information you're uncertain about"""

    args_schema = WebSearchSchema

    def run(self, arguments: Dict[str, Any]) -> str:
        if not DDGS_AVAILABLE:
            return "Error: Web search not available. Install with: pip install duckduckgo-search"

        query = arguments.get("query", "")
        max_results = min(max(arguments.get("max_results", 5), 1), 10)

        if not query:
            return "Error: No search query provided."

        try:
            results = self._search(query, max_results)

            if not results:
                return f"No results found for: {query}"

            # Format results
            output = f"Search results for: {query}\n\n"

            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("href", result.get("link", ""))
                snippet = result.get("body", result.get("snippet", ""))

                output += f"{i}. **{title}**\n"
                if url:
                    output += f"   URL: {url}\n"
                if snippet:
                    output += f"   {snippet}\n"
                output += "\n"

            return output.strip()

        except Exception as e:
            return f"Error searching: {str(e)}"

    def _search(self, query: str, max_results: int) -> List[Dict]:
        """Perform the actual search."""
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return results


class WebFetchSchema(BaseModel):
    url: str = Field(..., description="The URL to fetch content from")


class WebFetchTool(Tool):
    """
    Fetch and read content from a URL.

    Use this tool to read documentation pages, articles, or any web content.
    """

    name = "webfetch"
    description = """Fetch and read content from a specific URL. Use when:
- You need to read a documentation page
- User provides a specific URL to check
- You found a relevant URL from search results"""

    args_schema = WebFetchSchema

    def run(self, arguments: Dict[str, Any]) -> str:
        url = arguments.get("url", "")

        if not url:
            return "Error: No URL provided."

        try:
            import httpx
            from html import unescape
            import re

            # Fetch the page
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                html = response.text

            # Simple HTML to text conversion
            text = self._html_to_text(html)

            # Truncate if too long
            max_length = 4000
            if len(text) > max_length:
                text = text[:max_length] + "\n\n[Content truncated...]"

            return f"Content from {url}:\n\n{text}"

        except Exception as e:
            return f"Error fetching URL: {str(e)}"

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to readable text."""
        import re
        from html import unescape

        # Remove script and style elements
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML comments
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

        # Replace common elements with newlines
        html = re.sub(r'<br[^>]*>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<p[^>]*>', '\n\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<div[^>]*>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<h[1-6][^>]*>', '\n\n', html, flags=re.IGNORECASE)
        html = re.sub(r'</h[1-6]>', '\n', html, flags=re.IGNORECASE)
        html = re.sub(r'<li[^>]*>', '\n- ', html, flags=re.IGNORECASE)

        # Remove all other HTML tags
        html = re.sub(r'<[^>]+>', '', html)

        # Unescape HTML entities
        text = unescape(html)

        # Clean up whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        text = text.strip()

        return text
