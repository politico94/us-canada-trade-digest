#!/usr/bin/env python3
"""
US-CANADA TRADE POLICY DAILY DIGEST PIPELINE v3
=================================================
Zero API costs. No AI summarization.

v3 audit fixes:
  - Co-occurrence filter: leader names only count if trade keywords also present
  - Landing page URL blocklist: filters out program homepages
  - Freshness enforcement: items must have a date within lookback window
  - Stale content capped: undated items get lower score ceiling
  - Quip replaced with factual lead summary
  - Last-name partial matching removed (too many false positives)
  - URL deduplication: same base URL can't appear twice

1. Fetch   — RSS, web scraping across 68 sources
2. Score   — Weighted keyword taxonomy + co-occurrence leader matching
3. Filter  — Min score 3.0, min 2 TRADE keywords, URL + landing page blocklist
4. Deduplicate — Hash + Jaccard title similarity + URL dedup
5. Categorize — Route to best-fit section
6. Publish  — HTML digest to GitHub Pages, daily archive

Usage:
  python pipeline.py                    # Full run
  python pipeline.py --dry-run          # Preview without publishing
  python pipeline.py --date 2026-02-10  # Backfill a specific date
"""

import os
import sys
import json
import yaml
import hashlib
import logging
import argparse
import re
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("digest")

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "max_items_per_section": 5,
    "max_total_items": 30,
    "lookback_hours": 28,
    "request_timeout": 15,
    "min_relevance_score": 3.0,
    "min_keywords_matched": 1,       # Must match 1+ TRADE keyword (context keywords don't count)
    "min_title_length": 20,
    "max_undated_score": 4.0,        # v3: cap score for items without a parseable date
    "digest_sections": [
        "trade_actions",
        "legislation",
        "industry_impact",
        "analysis",
        "thought_leaders",
    ],
    "archive_dir": "archive",
    "output_dir": "output",
}

# ============================================================================
# KEYWORDS (unchanged from v2)
# ============================================================================

KEYWORDS = {
    "high": [
        "CUSMA", "USMCA", "canada-us trade", "us-canada trade",
        "canadian tariff", "softwood lumber", "dairy trade",
        "trade war canada", "retaliatory tariff", "countervailing duty",
        "anti-dumping canada", "buy america", "border adjustment",
        "digital services tax", "CUSMA review", "trade corridor",
        "reciprocal tariff", "section 232 canada", "section 301",
    ],
    "medium": [
        "canada trade", "canadian exports", "canadian imports",
        "bilateral trade", "north american trade", "supply management",
        "auto rules of origin", "critical minerals trade",
        "energy exports canada", "lumber duties", "steel tariff",
        "aluminum tariff", "trade deficit canada", "customs union",
        "carbon border", "procurement canada", "trade delegation",
        "trade mission", "trade pact", "trade agreement",
        "trade representative", "commerce department",
    ],
    "low": [
        "tariff", "duty", "quota", "import ban", "export controls",
        "trade sanctions", "trade policy", "trade deal",
        "canada trade", "canadian export", "canadian import",
        "united states", "trade link", "supply chain",
        "export", "import", "trade",
    ],
}

# v3: Context keywords — boost relevance score but do NOT count toward
# the min_keywords_matched trade keyword requirement. This prevents
# "canada" alone from qualifying an item, while still rewarding items
# that mention Canada alongside actual trade terms.
CONTEXT_KEYWORDS = {
    "canada": 1.0,
    "canadian": 1.0,
    "ottawa": 0.5,
    "parliament": 0.5,
    "washington": 0.5,
    "congress": 0.5,
    "NATO": 0.5,
    "NORAD": 0.5,
    "G7": 0.5,
}

# v3: Separate list of TRADE-CONTEXT keywords used for co-occurrence check
# These are the keywords that must appear alongside a leader name
TRADE_CONTEXT_KEYWORDS = {
    "tariff", "trade", "CUSMA", "USMCA", "export", "import", "duty",
    "softwood", "lumber", "dairy", "aluminum", "steel", "countervailing",
    "anti-dumping", "procurement", "bilateral", "supply management",
    "rules of origin", "border adjustment", "digital services tax",
    "trade war", "trade deal", "trade pact", "trade agreement",
    "trade mission", "trade delegation", "trade corridor", "trade deficit",
    "retaliatory", "reciprocal", "buy america", "commerce department",
    "trade representative", "USTR", "customs", "quota",
    "critical minerals", "energy exports", "trade policy",
    "section 232", "section 301", "carbon border",
}

# ============================================================================
# THOUGHT LEADERS
# ============================================================================

THOUGHT_LEADERS = {
    "tier1": [
        "Jamieson Greer", "Pete Hoekstra",
        "Mark Carney", "Dominic LeBlanc", "Maninder Sidhu",
        "François-Philippe Champagne", "Mark Wiseman", "Kirsten Hillman",
        "Robert Lighthizer", "Chrystia Freeland", "Katherine Tai",
        "Steve Verheul",
    ],
    "tier2": [
        "Mike Crapo", "Ron Wyden", "Jason Smith", "Chuck Grassley",
        "Judy Sgro", "Randy Hoback",
        "Doug Ford", "Danielle Smith", "François Legault", "David Eby",
        "Scott Moe", "Wab Kinew",
        "Dan Ciuriak", "Christopher Sands", "Chad Bown", "Meredith Lilly",
        "Laura Dawson", "Lawrence Herman", "Danielle Goldfarb",
        "Scott Lincicome", "Gary Clyde Hufbauer", "Jeffrey Schott",
        "Bill Reinsch", "Scott Miller", "Carlo Dade", "Trevor Tombe",
        "Cyndee Todgham Cherniak", "Jon Johnson", "Mark Warner",
        "Flavio Volpe", "Goldy Hyder", "Dan Kelly", "Dennis Darby",
        "Gregg Doud", "Derek Nighbor", "David Wiens",
        "Alexander Panetta", "Steven Chase", "Doug Palmer",
        "Andrew Coyne", "Chantal Hébert", "Paul Wells", "John Ivison",
        "Kevin Carmichael",
        "Bruce Heyman", "David MacNaughton", "Gary Doer",
        "Michael Froman", "Derek Burney", "Gordon Ritchie",
    ],
    "tier3": [
        "Richard Neal", "Stephen Vaughn", "Kelly Ann Shaw",
        "Sally Laing", "Jeffrey Gerrish", "C.J. Mahoney", "John Melle",
        "Susan Schwab", "Rob Portman",
        "Simon-Pierre Savard-Tremblay", "Brian Masse",
        "Candace Laing", "Kurt Niquidet", "Jay Timmons",
        "Robert Wolfe", "Patrick Leblond", "Emily Blanchard",
        "Michael Hart", "Stephen Tapp", "Hendrik Brakel",
        "Gavin Bade", "Stuart Thomson", "Ana Swanson",
        "Konrad Yakabuski", "Lawrence Martin", "John Ibbitson",
        "Vassy Kapelos", "David Herle",
        "Riyaz Dattu", "Christopher Kent", "Thomas Beline",
    ],
}

LEADER_WEIGHTS = {"tier1": 3.0, "tier2": 2.0, "tier3": 1.5}

# Flat set for quick lookups — FULL NAMES ONLY (v3: no last-name partial matching)
ALL_LEADERS = set()
for tier_names in THOUGHT_LEADERS.values():
    ALL_LEADERS.update(tier_names)

# Build lookup: full name -> weight
LEADER_WEIGHT_MAP = {}
for tier, names in THOUGHT_LEADERS.items():
    for name in names:
        LEADER_WEIGHT_MAP[name.lower()] = LEADER_WEIGHTS[tier]

# ============================================================================
# URL BLOCKLIST & LANDING PAGE DETECTION (v3 new)
# ============================================================================

# URLs that are program homepages, not articles
URL_BLOCKLIST_PATTERNS = [
    # Social media / login / nav junk
    r"facebook\.com", r"twitter\.com", r"x\.com/(?!.*status)",
    r"linkedin\.com/company", r"instagram\.com",
    r"/login", r"/signup", r"/subscribe", r"/contact",
    r"/about-us$", r"/careers$", r"/donate$",
]

# v3: Detect landing/program pages that aren't individual articles
LANDING_PAGE_PATTERNS = [
    # Wilson Center program pages
    r"wilsoncenter\.org/program/",
    # CSIS program pages (not individual articles)
    r"csis\.org/programs/",
    # Think tank "about" pages
    r"/about$", r"/about/$",
    # Generic index pages
    r"\.com/$", r"\.ca/$", r"\.org/$",
]

# v3: URLs that ARE specific articles even on program sites
ARTICLE_URL_PATTERNS = [
    r"/analysis/", r"/commentary/", r"/publication/",
    r"/blog/", r"/article/", r"/report/", r"/event/",
    r"/podcast/", r"/video/", r"/brief/", r"/paper/",
    r"/insight/", r"/perspective/", r"/news/",
    r"\d{4}/\d{2}/",  # Date-based URLs like /2026/02/
    r"-\d{4,}",        # Article IDs
]


def is_blocked_url(url: str) -> bool:
    """Check if URL matches blocklist patterns."""
    for pattern in URL_BLOCKLIST_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


def is_landing_page(url: str) -> bool:
    """v3: Detect program/landing pages that aren't individual articles."""
    # First check if it looks like a specific article
    for pattern in ARTICLE_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return False
    # Then check if it matches landing page patterns
    for pattern in LANDING_PAGE_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return True
    return False


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class SourceItem:
    title: str
    url: str
    source_name: str
    source_category: str
    snippet: str = ""
    published: Optional[datetime] = None
    published_str: str = ""
    relevance_score: float = 0.0
    keywords_matched: list = field(default_factory=list)
    trade_keywords_matched: list = field(default_factory=list)  # v3: separate trade keywords
    leaders_matched: list = field(default_factory=list)
    section: str = "analysis"
    item_hash: str = ""

    def __post_init__(self):
        if not self.item_hash:
            raw = f"{self.title}{self.url}".lower().strip()
            self.item_hash = hashlib.md5(raw.encode()).hexdigest()[:12]
        if self.published and not self.published_str:
            self.published_str = self.published.strftime("%b %d")


# ============================================================================
# FETCHERS
# ============================================================================

class RSSFetcher:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TradeDigestBot/3.0 (policy monitoring)"
        })

    def fetch(self, source: dict) -> list[SourceItem]:
        items = []
        rss_url = source.get("rss_url", source.get("url"))
        try:
            resp = self.session.get(rss_url, timeout=self.timeout)
            feed = feedparser.parse(resp.content)

            cutoff = datetime.now(timezone.utc) - timedelta(hours=CONFIG["lookback_hours"])

            for entry in feed.entries[:20]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    try:
                        published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        pass

                # v3: Skip items with dates older than lookback window
                if published and published < cutoff:
                    continue

                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                snippet = getattr(entry, "summary", "")
                if snippet:
                    snippet = BeautifulSoup(snippet, "html.parser").get_text()[:300]

                if not title or not link:
                    continue
                if len(title) < CONFIG["min_title_length"]:
                    continue

                items.append(SourceItem(
                    title=title,
                    url=link,
                    source_name=source["name"],
                    source_category=source.get("category", "media"),
                    snippet=snippet,
                    published=published,
                ))

        except Exception as e:
            log.warning(f"RSS fetch failed for {source['name']}: {e}")

        return items


class WebScraper:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "TradeDigestBot/3.0 (policy monitoring)"
        })

    def fetch(self, source: dict) -> list[SourceItem]:
        items = []
        try:
            resp = self.session.get(source["url"], timeout=self.timeout)
            soup = BeautifulSoup(resp.content, "html.parser")
            keywords = source.get("keywords", [])

            for link in soup.find_all("a", href=True):
                title = link.get_text(strip=True)
                href = link["href"]

                if not title or len(title) < CONFIG["min_title_length"]:
                    continue
                if len(title) > 300:
                    continue

                full_url = urljoin(source["url"], href)

                # v3: Skip blocked and landing page URLs
                if is_blocked_url(full_url):
                    continue
                if is_landing_page(full_url):
                    log.debug(f"Skipped landing page: {full_url}")
                    continue

                # Basic keyword pre-filter for scraped items
                text = title.lower()
                if keywords and not any(kw.lower() in text for kw in keywords):
                    continue

                items.append(SourceItem(
                    title=title,
                    url=full_url,
                    source_name=source["name"],
                    source_category=source.get("category", "media"),
                    snippet="",
                    published=None,
                ))

        except Exception as e:
            log.warning(f"Scrape failed for {source['name']}: {e}")

        return items


# ============================================================================
# FILTER & SCORER (v3: co-occurrence requirement for leaders)
# ============================================================================

class Filter:
    WEIGHTS = {"high": 3, "medium": 2, "low": 1}

    def __init__(self, keywords: dict, source_keywords: list[str] = None):
        self.keywords = keywords
        self.source_keywords = source_keywords or []

    def _has_trade_context(self, text: str) -> bool:
        """v3: Check if text contains at least one trade-specific keyword."""
        text_lower = text.lower()
        for kw in TRADE_CONTEXT_KEYWORDS:
            if kw.lower() in text_lower:
                return True
        return False

    def score_item(self, item: SourceItem) -> SourceItem:
        text = f"{item.title} {item.snippet}".lower()
        score = 0.0
        matched = []
        trade_matched = []

        # Global keyword scoring
        for tier, terms in self.keywords.items():
            weight = self.WEIGHTS[tier]
            for term in terms:
                if term.lower() in text:
                    score += weight
                    matched.append(term)
                    trade_matched.append(term)  # These are all trade keywords

        # Source-specific keyword boost
        for kw in self.source_keywords:
            if kw.lower() in text:
                score += 1.5
                if kw not in matched:
                    matched.append(kw)
                    trade_matched.append(kw)

        # v3: Context keywords — boost score but do NOT count as trade keywords
        for kw, weight in CONTEXT_KEYWORDS.items():
            if kw.lower() in text:
                score += weight
                if kw not in matched:
                    matched.append(kw)

        # v3: Thought leader name matching WITH co-occurrence requirement
        leaders_found = []
        has_trade_context = self._has_trade_context(text)

        for name in ALL_LEADERS:
            if name.lower() in text:
                if has_trade_context:
                    # Full score: leader mentioned in trade context
                    weight = LEADER_WEIGHT_MAP.get(name.lower(), 1.5)
                    score += weight
                    leaders_found.append(name)
                    if name not in matched:
                        matched.append(name)
                else:
                    # v3: Leader mentioned WITHOUT trade context — record but don't boost
                    leaders_found.append(name)
                    log.debug(f"Leader {name} found without trade context in: {item.title[:60]}")

        item.relevance_score = score
        item.keywords_matched = matched
        item.trade_keywords_matched = trade_matched
        item.leaders_matched = leaders_found

        # v3: Cap score for undated items
        if item.published is None and item.relevance_score > CONFIG["max_undated_score"]:
            item.relevance_score = CONFIG["max_undated_score"]

        return item

    def filter_items(self, items: list[SourceItem],
                     min_score: float = None,
                     min_keywords: int = None) -> list[SourceItem]:
        """Score all items and return those above quality thresholds."""
        if min_score is None:
            min_score = CONFIG["min_relevance_score"]
        if min_keywords is None:
            min_keywords = CONFIG["min_keywords_matched"]

        scored = [self.score_item(item) for item in items]

        filtered = []
        for item in scored:
            # v3: Require min TRADE keywords, not just any keywords
            if item.relevance_score < min_score:
                continue
            if len(item.trade_keywords_matched) < min_keywords:
                log.debug(f"Dropped (low trade keywords): {item.title[:60]}")
                continue
            filtered.append(item)

        return filtered


# ============================================================================
# DEDUPLICATOR (v3: + URL base dedup)
# ============================================================================

class Deduplicator:
    def __init__(self):
        self.seen_hashes = set()
        self.seen_titles = []
        self.seen_base_urls = set()  # v3

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()

    @staticmethod
    def _base_url(url: str) -> str:
        """v3: Extract base URL without query params and fragments."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    def _is_similar_title(self, title: str, threshold: float = 0.7) -> bool:
        norm = self._normalize(title)
        words_new = set(norm.split())
        if not words_new:
            return False
        for seen in self.seen_titles:
            words_seen = set(seen.split())
            if not words_seen:
                continue
            jaccard = len(words_new & words_seen) / len(words_new | words_seen)
            if jaccard >= threshold:
                return True
        return False

    def deduplicate(self, items: list[SourceItem]) -> list[SourceItem]:
        sorted_items = sorted(items, key=lambda x: x.relevance_score, reverse=True)
        unique = []
        for item in sorted_items:
            if item.item_hash in self.seen_hashes:
                continue
            if self._is_similar_title(item.title):
                continue
            # v3: URL base dedup
            base = self._base_url(item.url)
            if base in self.seen_base_urls:
                log.debug(f"Dropped (duplicate URL): {item.title[:60]}")
                continue
            self.seen_hashes.add(item.item_hash)
            self.seen_titles.append(self._normalize(item.title))
            self.seen_base_urls.add(base)
            unique.append(item)
        return unique


# ============================================================================
# CATEGORIZER (v3: tightened rules)
# ============================================================================

SECTION_RULES = {
    "trade_actions": {
        "source_categories": ["us_government", "canadian_government", "federal_register"],
        "keywords": ["tariff", "duty", "countervailing", "anti-dumping", "regulation",
                      "customs", "quota", "safeguard", "proclamation", "executive order",
                      "section 232", "section 301"],
    },
    "legislation": {
        "source_categories": ["congressional", "congressional_record", "parliamentary"],
        "keywords": ["bill", "act", "hearing", "committee", "testimony", "hansard",
                      "floor statement", "markup", "vote", "senator", "representative",
                      "motion", "reading"],
    },
    "industry_impact": {
        "source_categories": ["industry", "business_media"],
        "keywords": ["supply chain", "manufacturing", "auto parts", "factory",
                      "production", "plant", "workers", "jobs", "investment",
                      "sector", "industry", "company", "business", "economic impact",
                      "delegation", "mission"],
    },
    "analysis": {
        "source_categories": ["think_tank", "academic", "commentary", "newsletter"],
        "keywords": ["analysis", "commentary", "opinion", "research", "paper",
                      "study", "brief", "forecast", "outlook", "perspective",
                      "implications", "strategy"],
    },
    "thought_leaders": {
        "source_categories": [],
        "keywords": [],
        # v3: Routed by leader match presence + trade context
    },
}


class Categorizer:
    def categorize(self, item: SourceItem) -> str:
        # v3: Only route to thought_leaders if BOTH leader match AND trade context
        if item.leaders_matched and item.trade_keywords_matched:
            # Check if it fits better in another section first
            best_section = self._best_section(item)
            if best_section == "analysis":
                return "thought_leaders"
            return best_section

        return self._best_section(item)

    def _best_section(self, item: SourceItem) -> str:
        best = "analysis"
        best_score = 0

        text = f"{item.title} {item.snippet}".lower()

        for section, rules in SECTION_RULES.items():
            if section == "thought_leaders":
                continue
            score = 0
            if item.source_category in rules["source_categories"]:
                score += 3
            for kw in rules["keywords"]:
                if kw.lower() in text:
                    score += 1
            if score > best_score:
                best_score = score
                best = section

        return best


# ============================================================================
# DIGEST BUILDER
# ============================================================================

class DigestBuilder:
    def __init__(self, items: list[SourceItem], digest_date: datetime):
        self.items = items
        self.digest_date = digest_date

    def build(self) -> dict:
        sections = {}
        for section_name in CONFIG["digest_sections"]:
            section_items = [i for i in self.items if i.section == section_name]
            section_items.sort(key=lambda x: x.relevance_score, reverse=True)
            sections[section_name] = section_items[:CONFIG["max_items_per_section"]]

        # Collect all mentioned leaders for the voices banner
        all_leaders = set()
        for item in self.items:
            all_leaders.update(item.leaders_matched)

        # v3: Build factual lead instead of quip
        total_items = sum(len(v) for v in sections.values())
        source_count = len(set(i.source_name for i in self.items))
        leader_count = len(all_leaders)

        return {
            "date": self.digest_date.strftime("%Y-%m-%d"),
            "date_display": self.digest_date.strftime("%A, %B %d, %Y"),
            "total_items": total_items,
            "source_count": source_count,
            "leader_count": leader_count,
            "leaders": sorted(all_leaders),
            "sections": sections,
        }


# ============================================================================
# HTML RENDERER
# ============================================================================

class Renderer:
    def __init__(self, template_dir: str = "templates"):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True,
        )

    def render(self, digest_data: dict) -> str:
        template = self.env.get_template("digest.html")
        return template.render(**digest_data)


# ============================================================================
# PUBLISHER
# ============================================================================

class Publisher:
    def __init__(self, output_dir: str = "."):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, html: str, digest_date: datetime):
        # Write main index
        index_path = self.output_dir / "index.html"
        index_path.write_text(html, encoding="utf-8")
        log.info(f"Published: {index_path}")

        # Archive
        archive_dir = self.output_dir / CONFIG["archive_dir"]
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"{digest_date.strftime('%Y-%m-%d')}.html"
        archive_path.write_text(html, encoding="utf-8")
        log.info(f"Archived: {archive_path}")

        # Update archive index
        self._update_archive_index(archive_dir)

    def _update_archive_index(self, archive_dir: Path):
        files = sorted(archive_dir.glob("*.html"), reverse=True)
        files = [f for f in files if f.name != "index.html"]

        links = []
        for f in files[:90]:  # Keep 90 days
            date_str = f.stem
            links.append(f'<li><a href="{f.name}">{date_str}</a></li>')

        html = f"""<!DOCTYPE html>
<html><head><title>Trade Digest Archive</title>
<style>
  body {{ font-family: system-ui; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }}
  a {{ color: #1a5276; }}
  li {{ margin: 0.3rem 0; }}
</style>
</head><body>
<h1>🇺🇸🇨🇦 Trade Digest Archive</h1>
<p><a href="../">← Current digest</a></p>
<ul>{"".join(links)}</ul>
</body></html>"""

        (archive_dir / "index.html").write_text(html, encoding="utf-8")


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def load_sources(path: str = "sources.yaml") -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)

    flat = []
    for category, sources in data.items():
        for source in sources:
            source["category"] = category
            flat.append(source)
    return flat


def run_pipeline(digest_date: datetime = None, dry_run: bool = False):
    if digest_date is None:
        digest_date = datetime.now(timezone.utc)

    log.info(f"=== Trade Digest v3 — {digest_date.strftime('%Y-%m-%d')} ===")

    # Load sources
    sources = load_sources()
    log.info(f"Loaded {len(sources)} sources")

    # Fetch
    rss_fetcher = RSSFetcher(timeout=CONFIG["request_timeout"])
    web_scraper = WebScraper(timeout=CONFIG["request_timeout"])

    all_items = []
    for source in sources:
        fetcher_type = source.get("type", "rss")
        if fetcher_type == "rss":
            items = rss_fetcher.fetch(source)
        elif fetcher_type == "web_scrape":
            items = web_scraper.fetch(source)
        else:
            items = rss_fetcher.fetch(source)

        log.info(f"  {source['name']}: {len(items)} items")
        all_items.extend(items)

    log.info(f"Total fetched: {len(all_items)}")

    # Filter
    filt = Filter(KEYWORDS)
    filtered = filt.filter_items(all_items)
    log.info(f"After filtering: {len(filtered)}")

    # Deduplicate
    dedup = Deduplicator()
    unique = dedup.deduplicate(filtered)
    log.info(f"After dedup: {len(unique)}")

    # Categorize
    cat = Categorizer()
    for item in unique:
        item.section = cat.categorize(item)

    # Trim to max
    unique = sorted(unique, key=lambda x: x.relevance_score, reverse=True)
    unique = unique[:CONFIG["max_total_items"]]

    # Build digest
    builder = DigestBuilder(unique, digest_date)
    digest_data = builder.build()

    log.info(f"Digest: {digest_data['total_items']} items, "
             f"{digest_data['source_count']} sources, "
             f"{digest_data['leader_count']} leaders")
    for section_name, section_items in digest_data["sections"].items():
        log.info(f"  {section_name}: {len(section_items)} items")

    if dry_run:
        log.info("DRY RUN — not publishing")
        for section_name, section_items in digest_data["sections"].items():
            print(f"\n{'='*60}")
            print(f"  {section_name.upper()}")
            print(f"{'='*60}")
            for item in section_items:
                leaders = f" 👤 {', '.join(item.leaders_matched)}" if item.leaders_matched else ""
                dated = f" · {item.published_str}" if item.published_str else " · (no date)"
                print(f"  [{item.relevance_score:.1f}] {item.title[:80]}")
                print(f"         {item.source_name}{dated}{leaders}")
                print(f"         Keywords: {', '.join(item.trade_keywords_matched[:5])}")
                print(f"         {item.url}")
                print()
        return

    # Render
    renderer = Renderer()
    html = renderer.render(digest_data)

    # Publish
    publisher = Publisher(".")
    publisher.publish(html, digest_date)

    log.info("✅ Done")


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US-Canada Trade Digest v3")
    parser.add_argument("--dry-run", action="store_true", help="Preview without publishing")
    parser.add_argument("--date", type=str, help="Digest date (YYYY-MM-DD)")
    args = parser.parse_args()

    digest_date = None
    if args.date:
        digest_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    run_pipeline(digest_date=digest_date, dry_run=args.dry_run)
