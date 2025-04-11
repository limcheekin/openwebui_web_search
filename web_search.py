"""
title: Web Search using SearXNG and Scrape first N Pages
author: constLiakos with enhancements by justinh-rahb and ther3zz
funding_url: https://github.com/EntropyYue/web_search
version: 0.4.4
license: MIT
"""

import requests
import json
from bs4 import BeautifulSoup
import concurrent.futures
from urllib.parse import urlparse
import re
import unicodedata
from pydantic import BaseModel, Field
from typing import Callable, Any


class HelpFunctions:
    def __init__(self):
        pass

    def get_base_url(self, url):
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return base_url

    def generate_excerpt(self, content, max_length=200):
        return content[:max_length] + "..." if len(content) > max_length else content

    def format_text(self, original_text, valves):
        soup = BeautifulSoup(original_text, "html.parser")
        formatted_text = soup.get_text(separator=" ", strip=True)
        formatted_text = unicodedata.normalize("NFKC", formatted_text)
        formatted_text = re.sub(r"\s+", " ", formatted_text)
        formatted_text = formatted_text.strip()
        formatted_text = self.remove_emojis(formatted_text)
        if valves.REMOVE_LINKS:
            formatted_text = self.replace_urls_with_text(formatted_text)
        return formatted_text

    def remove_emojis(self, text):
        return "".join(c for c in text if not unicodedata.category(c).startswith("So"))

    def replace_urls_with_text(self, text, replacement="(links)"):
        pattern = r"\(https?://[^\s]+\)"
        return re.sub(pattern, replacement, text)

    def process_search_result(self, result, valves):
        title_site = self.remove_emojis(result["title"])
        url_site = result["url"]
        snippet = result.get("content", "")

        # Check if the website is in the ignored list, but only if IGNORED_WEBSITES is not empty
        if valves.IGNORED_WEBSITES:
            base_url = self.get_base_url(url_site)
            if any(
                ignored_site.strip() in base_url
                for ignored_site in valves.IGNORED_WEBSITES.split(",")
            ):
                return None

        try:
            response_site = requests.get(
                valves.JINA_READER_BASE_URL + url_site, timeout=20
            )
            response_site.raise_for_status()
            html_content = response_site.text

            soup = BeautifulSoup(html_content, "html.parser")
            content_site = soup.get_text(separator=" ", strip=True)
            if valves.JINA_READER_BASE_URL != "":
                content_site = self.format_text(content_site, valves)

            truncated_content = self.truncate_to_n_words(
                content_site, valves.PAGE_CONTENT_WORDS_LIMIT
            )

            return {
                "title": title_site,
                "url": url_site,
                "content": truncated_content,
                "snippet": self.remove_emojis(snippet),
            }

        except requests.exceptions.RequestException:
            return None

    def truncate_to_n_words(self, text, token_limit):
        tokens = text.split()
        truncated_tokens = tokens[:token_limit]
        return " ".join(truncated_tokens)


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def emit(
        self,
        description="Unknown",
        status="in_progress",
        done=False,
        action="",
        urls=[],
    ):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                        "action": action,
                        "urls": urls,
                    },
                }
            )


class Tools:
    class Valves(BaseModel):
        SEARXNG_ENGINE_API_BASE_URL: str = Field(
            default="https://example.com/search",
            description="Base URL of the search engine",
        )

        IGNORED_WEBSITES: str = Field(
            default="",
            description="Comma-separated list of websites to ignore",
        )

        RETURNED_SCRAPPED_PAGES_NO: int = Field(
            default=3,
            description="Number of search engine results to analyze",
        )

        SCRAPPED_PAGES_NO: int = Field(
            default=5,
            description="Total number of paginated pages. Ideally greater than one of the returned pages",
        )

        PAGE_CONTENT_WORDS_LIMIT: int = Field(
            default=5000,
            description="Limit the number of words per page",
        )

        CITATION_LINKS: bool = Field(
            default=False,
            description="If True, sends custom citations with links",
        )

        JINA_READER_BASE_URL: str = Field(
            default="https://r.jina.ai/",
            description="Base URL of the Jina Reader",
        )

        REMOVE_LINKS: bool = Field(
            default=True,
            description="Whether to remove links in the retrieved content",
        )


    def __init__(self):
        self.valves = self.Valves()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

    async def search_web(
        self,
        query: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Search the web and retrieve the content of relevant pages. Used to search for unknown knowledge, news, information, public contact info, weather, etc.

        :params query: Keywords used in the search

        :return: The content of the pages in JSON format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)

        await emitter.emit(f"Searching: {query}")

        search_engine_url = self.valves.SEARXNG_ENGINE_API_BASE_URL

        # Ensure RETURNED_SCRAPPED_PAGES_NO does not exceed SCRAPPED_PAGES_NO
        if self.valves.RETURNED_SCRAPPED_PAGES_NO > self.valves.SCRAPPED_PAGES_NO:
            self.valves.RETURNED_SCRAPPED_PAGES_NO = self.valves.SCRAPPED_PAGES_NO

        params = {
            "q": query,
            "format": "json",
            "number_of_results": self.valves.RETURNED_SCRAPPED_PAGES_NO,
        }

        try:
            await emitter.emit("Sending query to search engine")
            resp = requests.get(
                search_engine_url, params=params, headers=self.headers, timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            limited_results = results[: self.valves.SCRAPPED_PAGES_NO]
            await emitter.emit(f"Found {len(limited_results)} search results")

        except requests.exceptions.RequestException as e:
            await emitter.emit(
                status="error",
                description=f"Search error: {str(e)}",
                done=True,
            )
            return json.dumps({"error": str(e)})

        results_json = []
        if limited_results:
            await emitter.emit("Processing search results")

            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(
                            functions.process_search_result, result, self.valves
                        )
                        for result in limited_results
                    ]

                    processed_count = 0
                    for future in concurrent.futures.as_completed(futures):
                        result_json = future.result()
                        if result_json:
                            try:
                                results_json.append(result_json)
                                processed_count += 1
                                await emitter.emit(
                                    f"Processing page {processed_count}/{len(limited_results)}",
                                )
                            except (TypeError, ValueError, Exception) as e:
                                print(f"Processing error: {str(e)}")
                                continue
                        if len(results_json) >= self.valves.RETURNED_SCRAPPED_PAGES_NO:
                            break

            except BaseException as e:
                await emitter.emit(
                    status="error",
                    description=f"Processing error: {str(e)}",
                    done=True,
                )

            results_json = results_json[: self.valves.RETURNED_SCRAPPED_PAGES_NO]

            if self.valves.CITATION_LINKS and __event_emitter__:
                if len(results_json):
                    for result in results_json:
                        await __event_emitter__(
                            {
                                "type": "citation",
                                "data": {
                                    "document": [result["content"]],
                                    "metadata": [{"source": result["url"]}],
                                    "source": {"name": result["title"]},
                                },
                            }
                        )

        urls = []
        for result in results_json:
            urls.append(result["url"])

        await emitter.emit(
            status="complete",
            description=f"Found {len(results_json)} search results",
            done=True,
            action="web_search",
            urls=urls,
        )

        return json.dumps(results_json, indent=4, ensure_ascii=False)

    async def get_website(
        self, url: str, __event_emitter__: Callable[[dict], Any] = None
    ) -> str:
        """
        Open the input website and retrieve its content

        :params url: Website to open

        :return: The content of the website in JSON format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)

        await emitter.emit(f"Fetching content: {url}")

        results_json = []

        try:
            response_site = requests.get(
                self.valves.JINA_READER_BASE_URL + url,
                headers=self.headers,
                timeout=120,
            )
            response_site.raise_for_status()
            html_content = response_site.text

            soup = BeautifulSoup(html_content, "html.parser")

            page_title = soup.title.string if soup.title else "No title found"
            page_title = unicodedata.normalize("NFKC", page_title.strip())
            page_title = functions.remove_emojis(page_title)
            title_site = page_title
            url_site = url
            content_site = functions.format_text(
                soup.get_text(separator=" ", strip=True), self.valves
            )

            truncated_content = functions.truncate_to_n_words(
                content_site, self.valves.PAGE_CONTENT_WORDS_LIMIT
            )

            result_site = {
                "title": title_site,
                "url": url_site,
                "content": truncated_content,
                "excerpt": functions.generate_excerpt(content_site),
            }

            results_json.append(result_site)

            if self.valves.CITATION_LINKS and __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "citation",
                        "data": {
                            "document": [truncated_content],
                            "metadata": [{"source": url_site}],
                            "source": {"name": title_site},
                        },
                    }
                )

            await emitter.emit(
                status="complete",
                description="Fetched and processed content successfully",
                done=True,
            )

        except requests.exceptions.RequestException as e:
            results_json.append(
                {
                    "url": url,
                    "content": f"Failed to fetch content: {str(e)}",
                }
            )

            await emitter.emit(
                status="error",
                description=f"Fetch content error: {str(e)}",
                done=True,
            )

        return json.dumps(results_json, indent=4, ensure_ascii=False)
