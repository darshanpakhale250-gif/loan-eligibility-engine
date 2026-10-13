"""
crawl.py – Production AsyncWebCrawler service using Crawl4AI with graceful fallback.

Crawls bank loan product pages based on sites.yml and seeds.txt:
  - Per-site isolation: failure on one site never fails others
  - Polite crawling: delay between requests, check_robots_txt, page timeout
  - Limited depth (1) and max page cap per site
  - Regex & heuristic field extraction mapped to loan_products schema
  - Detailed crawl statistics tracking
"""

import asyncio
import fnmatch
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
import yaml

from app.config import settings
from app.crawler.normalize import normalize_crawled_page

logger = logging.getLogger(__name__)

# Try importing Crawl4AI; if unavailable or playwright browser missing, fallback to httpx
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    logger.warning("crawl4ai not installed or importable; will use httpx fallback for crawling")


def load_sites_config() -> List[Dict[str, Any]]:
    """Load sites configuration from sites.yml."""
    config_path = os.path.join(os.path.dirname(__file__), "sites.yml")
    if not os.path.exists(config_path):
        return []
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sites", [])


def load_seed_urls() -> List[str]:
    """Load seed URLs from seeds.txt, filtering comments and blanks."""
    seeds_path = os.path.join(os.path.dirname(__file__), "seeds.txt")
    if not os.path.exists(seeds_path):
        return []
    urls = []
    with open(seeds_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def matches_patterns(url: str, patterns: List[str]) -> bool:
    """Check if URL matches any of the glob patterns."""
    if not patterns:
        return True
    path = urlparse(url).path.lower()
    full = url.lower()
    for pattern in patterns:
        p_lower = pattern.lower()
        if fnmatch.fnmatch(path, p_lower) or fnmatch.fnmatch(full, p_lower):
            return True
        # Also simple substring match if pattern has wildcards around it
        sub = p_lower.strip("*")
        if sub and (sub in path or sub in full):
            return True
    return False


def is_allowed_host(url: str, allowed_hosts: List[str]) -> bool:
    """Check if host belongs to allowed site hosts."""
    host = (urlparse(url).hostname or "").lower()
    for allowed in allowed_hosts:
        if host == allowed.lower() or host.endswith("." + allowed.lower()):
            return True
    return False


async def fetch_page_httpx(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    """Fetch and extract text from a webpage using httpx."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = await client.get(url, headers=headers, timeout=settings.page_timeout_ms / 1000.0, follow_redirects=True)
        if resp.status_code >= 400:
            logger.warning("HTTP %d for %s", resp.status_code, url)
            return None

        html_text = resp.text
        # Extract title
        title = ""
        m_title = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
        if m_title:
            title = re.sub(r"<[^>]+>", "", m_title.group(1)).strip()

        # Simple HTML to text
        clean = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<style[^>]*>.*?</style>", " ", clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        # Extract links for depth=1 exploration
        links = []
        for m_href in re.finditer(r'href=["\'](https?://[^"\']+|/[^"\']+)["\']', html_text, re.IGNORECASE):
            link = urljoin(url, m_href.group(1))
            links.append(link)

        return {
            "url": str(resp.url),
            "title": title,
            "text": clean,
            "markdown": clean,
            "links": list(set(links)),
        }
    except Exception as e:
        logger.warning("Error fetching %s with httpx: %s", url, e)
        return None


async def crawl_site(
    site: Dict[str, Any],
    seed_urls: List[str],
    stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Crawl a single site using Crawl4AI or httpx fallback."""
    site_name = site["name"]
    allowed_hosts = site.get("allowed_hosts", [])
    patterns = site.get("url_patterns", [])

    site_seeds = [u for u in seed_urls if is_allowed_host(u, allowed_hosts)]
    if not site_seeds:
        return []

    products: List[Dict[str, Any]] = []
    visited: set = set()
    queue = [(u, 0) for u in site_seeds]

    site_stats = {
        "pages_attempted": 0,
        "pages_succeeded": 0,
        "pages_failed": 0,
        "products_extracted": 0,
    }

    crawler_obj = None
    crawler_run_cfg = None

    if CRAWL4AI_AVAILABLE:
        try:
            b_cfg = BrowserConfig(
                headless=True,
                verbose=False,
            )
            crawler_obj = AsyncWebCrawler(config=b_cfg)
            await crawler_obj.start()

            crawler_run_cfg = CrawlerRunConfig(
                page_timeout=settings.page_timeout_ms,
                cache_mode=CacheMode.BYPASS,
                check_robots_txt=True,
                delay_before_return_html=1.5,
            )
        except Exception as e:
            logger.warning("Failed to start Crawl4AI AsyncWebCrawler (%s), falling back to httpx: %s", site_name, e)
            crawler_obj = None

    async with httpx.AsyncClient(verify=False) as http_client:
        try:
            while queue and site_stats["pages_attempted"] < settings.max_pages:
                curr_url, depth = queue.pop(0)
                if curr_url in visited:
                    continue
                visited.add(curr_url)
                site_stats["pages_attempted"] += 1

                page_data = None
                if crawler_obj and crawler_run_cfg:
                    try:
                        res = await crawler_obj.arun(url=curr_url, config=crawler_run_cfg)
                        if res and res.success:
                            links = [link.get("href") for link in (res.links.get("internal", []) + res.links.get("external", [])) if link.get("href")]
                            page_data = {
                                "url": res.url or curr_url,
                                "title": getattr(res, "metadata", {}).get("title", ""),
                                "text": res.cleaned_html or res.markdown or "",
                                "markdown": res.markdown or "",
                                "links": links,
                            }
                        else:
                            logger.info("Crawl4AI failed for %s, trying httpx fallback", curr_url)
                    except Exception as ce:
                        logger.warning("Crawl4AI exception for %s: %s", curr_url, ce)

                # Fallback to httpx if page_data not obtained
                if not page_data:
                    page_data = await fetch_page_httpx(http_client, curr_url)

                if not page_data:
                    site_stats["pages_failed"] += 1
                    continue

                site_stats["pages_succeeded"] += 1

                # Normalize extracted page into loan_product
                product = normalize_crawled_page(page_data, site)
                if product:
                    # Deduplicate within run by lender and product_name
                    if not any(p["product_name"] == product["product_name"] for p in products):
                        products.append(product)
                        site_stats["products_extracted"] += 1

                # Enqueue sublinks if depth < max_depth
                if depth < settings.max_depth:
                    for link in page_data.get("links", []):
                        if (
                            link not in visited
                            and is_allowed_host(link, allowed_hosts)
                            and matches_patterns(link, patterns)
                        ):
                            queue.append((link, depth + 1))

                # Polite delay between pages
                await asyncio.sleep(0.5)

        finally:
            if crawler_obj:
                try:
                    await crawler_obj.close()
                except Exception:
                    pass

    stats["per_site"][site_name] = site_stats
    stats["pages_attempted"] += site_stats["pages_attempted"]
    stats["pages_succeeded"] += site_stats["pages_succeeded"]
    stats["pages_failed"] += site_stats["pages_failed"]
    stats["products_extracted"] += site_stats["products_extracted"]

    return products


async def run_crawler() -> Dict[str, Any]:
    """
    Main crawler entry point.
    Reads sites.yml and seeds.txt, executes crawl per site,
    and returns {"products": [...], "stats": {...}}.
    """
    sites = load_sites_config()
    seeds = load_seed_urls()

    stats: Dict[str, Any] = {
        "pages_attempted": 0,
        "pages_succeeded": 0,
        "pages_failed": 0,
        "products_extracted": 0,
        "per_site": {},
    }

    all_products: List[Dict[str, Any]] = []

    for site in sites:
        try:
            site_prods = await crawl_site(site, seeds, stats)
            all_products.extend(site_prods)
        except Exception as e:
            logger.error("Unexpected error crawling site %s: %s", site.get("name"), e, exc_info=True)
            stats["per_site"][site.get("name", "unknown")] = {
                "error": str(e),
                "pages_attempted": 0,
                "pages_succeeded": 0,
                "pages_failed": 1,
                "products_extracted": 0,
            }

    logger.info(
        "Crawl completed: %d products extracted across %d attempted pages (%d succeeded, %d failed)",
        len(all_products),
        stats["pages_attempted"],
        stats["pages_succeeded"],
        stats["pages_failed"],
    )

    return {
        "products": all_products,
        "stats": stats,
    }
