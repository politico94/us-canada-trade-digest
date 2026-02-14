#!/usr/bin/env python3
"""
US-CANADA TRADE POLICY DAILY DIGEST PIPELINE v2
=================================================
Zero API costs. No Anthropic key needed.

v2 improvements:
  - Thought Leader Watch section (100+ tracked voices)
  - Quality filters: min score 3.0, min 2 keywords, URL blocklist
  - Name-based relevance boost for key trade policy figures
  - Expanded source coverage (newsletters, Substacks, podcasts)

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
import smtplib
import re
import random
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG = {
    "max_items_per_section": 5,
    "max_total_items": 35,
    "lookback_hours": 28,
    "request_timeout": 15,
    "min_relevance_score": 3.0,     # v2: raised from 1.0 to cut noise
    "min_keywords_matched": 2,       # v2: require at least 2 keyword hits
    "min_title_length": 20,          # v2: raised from 10 to skip nav junk
    "digest_sections": [
        "trade_actions",
        "legislation",
        "diplomatic",
        "industry_impact",
        "analysis",
        "disputes",
        "thought_leaders",           # v2: NEW — key voices in the debate
    ],
    "email_recipients": [],
    "archive_dir": "archive",
    "output_dir": "output",
}

# v2: URL blocklist — domains that produce false positives
URL_BLOCKLIST = [
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "tiktok.com",
    "login.", "signin.", "signup.", "cart.", "checkout.",
    "privacy-policy", "terms-of-service", "cookie-policy",
    "careers.", "jobs.", "about-us",
    "mailto:", "javascript:", "tel:",
]

# ============================================================================
# KEYWORDS — Trade policy taxonomy (weighted for relevance scoring)
# ============================================================================

KEYWORDS = {
    # Core terms (weight 3)
    "high": [
        "CUSMA", "USMCA", "canada-us trade", "us-canada trade",
        "canadian tariff", "softwood lumber", "dairy trade",
        "trade war canada", "retaliatory tariff", "countervailing duty",
        "anti-dumping canada", "buy america", "border adjustment",
        "digital services tax", "CUSMA review", "trade corridor",
        "CUSMA joint review", "section 232", "section 301",
        "tariff-rate quota", "one canadian economy",
        "team canada trade", "buy canadian",
    ],
    # Important terms (weight 2)
    "medium": [
        "canada trade", "canadian exports", "canadian imports",
        "bilateral trade", "north american trade", "supply management",
        "auto rules of origin", "critical minerals trade",
        "energy exports canada", "lumber duties", "steel tariff",
        "aluminum tariff", "trade deficit canada", "customs union",
        "carbon border", "procurement canada",
        "25 percent tariff", "25% tariff",
        "trade mission canada", "trade negotiation canada",
        "fortress north america", "north american integration",
    ],
    # Contextual terms (weight 1)
    "low": [
        "canada", "canadian", "Ottawa", "Carney", "Freeland",
        "trade representative", "commerce department",
        "tariff", "duty", "quota", "import", "export",
        "NATO", "NORAD", "five eyes", "G7",
        "Greer", "LeBlanc", "Champagne",
    ],
}

# ============================================================================
# v2: THOUGHT LEADERS — 100+ tracked voices in US-Canada trade policy
# ============================================================================

# Names are scored separately — a name match boosts relevance and can
# route items to the Thought Leader Watch section.

THOUGHT_LEADERS = {
    # --- Tier 1: Highest-profile voices (weight 3) ---
    "tier1": [
        # Current US officials
        "Jamieson Greer", "Pete Hoekstra",
        # Current Canadian officials
        "Mark Carney", "Dominic LeBlanc", "Maninder Sidhu",
        "François-Philippe Champagne", "Mark Wiseman", "Kirsten Hillman",
        # Former heavyweights
        "Robert Lighthizer", "Chrystia Freeland", "Katherine Tai",
        # Key negotiators
        "Steve Verheul",
    ],

    # --- Tier 2: Major analysts, columnists, industry voices (weight 2) ---
    "tier2": [
        # US Congress
        "Mike Crapo", "Ron Wyden", "Jason Smith", "Chuck Grassley",
        # Canadian Parliament
        "Judy Sgro", "Randy Hoback",
        # Provincial premiers
        "Doug Ford", "Danielle Smith", "François Legault", "David Eby",
        "Scott Moe", "Wab Kinew",
        # Think tank / academic
        "Dan Ciuriak", "Christopher Sands", "Chad Bown", "Meredith Lilly",
        "Laura Dawson", "Lawrence Herman", "Danielle Goldfarb",
        "Scott Lincicome", "Gary Clyde Hufbauer", "Jeffrey Schott",
        "Bill Reinsch", "Scott Miller", "Carlo Dade", "Trevor Tombe",
        # Trade lawyers
        "Cyndee Todgham Cherniak", "Jon Johnson", "Mark Warner",
        # Industry
        "Flavio Volpe", "Goldy Hyder", "Dan Kelly", "Dennis Darby",
        "Gregg Doud", "Derek Nighbor", "David Wiens",
        # Journalists
        "Alexander Panetta", "Steven Chase", "Doug Palmer",
        "Andrew Coyne", "Chantal Hébert", "Paul Wells", "John Ivison",
        "Kevin Carmichael",
        # Former officials still active
        "Bruce Heyman", "David MacNaughton", "Gary Doer",
        "Michael Froman", "Derek Burney", "Gordon Ritchie",
    ],

    # --- Tier 3: Notable voices, less frequent mentions (weight 1.5) ---
    "tier3": [
        # More US figures
        "Richard Neal", "Stephen Vaughn", "Kelly Ann Shaw",
        "Sally Laing", "Jeffrey Gerrish", "C.J. Mahoney", "John Melle",
        "Susan Schwab", "Rob Portman",
        # More Canadian figures
        "Simon-Pierre Savard-Tremblay", "Brian Masse",
        "Candace Laing", "Kurt Niquidet", "Jay Timmons",
        # More analysts
        "Robert Wolfe", "Patrick Leblond", "Emily Blanchard",
        "Michael Hart", "Stephen Tapp", "Hendrik Brakel",
        # More journalists
        "Gavin Bade", "Stuart Thomson", "Ana Swanson",
        "Konrad Yakabuski", "Lawrence Martin", "John Ibbitson",
        "Vassy Kapelos", "David Herle",
        # Trade lawyers
        "Riyaz Dattu", "Christopher Kent", "Thomas Beline",
    ],
}

LEADER_WEIGHTS = {"tier1": 3.0, "tier2": 2.0, "tier3": 1.5}

# Flat set for quick lookups
ALL_LEADERS = set()
for tier_names in THOUGHT_LEADERS.values():
    ALL_LEADERS.update(tier_names)

# Build lookup: name -> weight
LEADER_WEIGHT_MAP = {}
for tier, names in THOUGHT_LEADERS.items():
    for name in names:
        LEADER_WEIGHT_MAP[name.lower()] = LEADER_WEIGHTS[tier]
        # Also index last names for partial matching
        parts = name.split()
        if len(parts) >= 2:
            LEADER_WEIGHT_MAP[parts[-1].lower()] = LEADER_WEIGHTS[tier] * 0.5

# Trade policy quips — no AI needed
TRADE_QUIPS = [
    "Why did the tariff go to therapy? It had too many duties.",
    "CUSMA walks into a bar. The bartender says, 'Aren't you NAFTA?' It replies, 'I've rebranded.'",
    "What's a trade negotiator's favourite dance? The two-step — one forward, two back.",
    "Softwood lumber disputes are like fruitcake — nobody asked for them and they never go away.",
    "Why don't tariffs ever win arguments? Because they always raise the stakes.",
    "What did Canada say to the US tariff? 'That's a duty I didn't sign up for.'",
    "Trade corridors are just highways with lobbyists.",
    "Why is the Federal Register like a mystery novel? Buried in it is something that will ruin your day.",
    "USMCA: three countries, two languages, one acronym nobody can pronounce naturally.",
    "What do trade lawyers and hockey players have in common? They both get paid to fight over boards.",
    "Why did the countervailing duty cross the border? To offset the subsidy on the other side.",
    "The Congressional Record is proof that even in Washington, someone is talking about Canada.",
    "Supply management: where the real dairy drama happens.",
    "Rules of origin are just trade policy's way of asking 'but where are you really from?'",
    "Why did the CUSMA review walk into a bar? It was looking for a joint resolution.",
    "Mark Wiseman arrives as ambassador tomorrow. The trade lobby's Valentine's Day gift: another person to brief.",
]

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class SourceItem:
    title: str
    url: str
    source_name: str
    source_category: str
    published: Optional[datetime] = None
    snippet: str = ""
    relevance_score: float = 0.0
    keywords_matched: list = field(default_factory=list)
    leaders_matched: list = field(default_factory=list)  # v2: track which leaders mentioned
    digest_section: str = ""
    item_hash: str = ""

    def __post_init__(self):
        raw = f"{self.title.lower().strip()}{self.url.strip()}"
        self.item_hash = hashlib.md5(raw.encode()).hexdigest()


# ============================================================================
# v2: URL QUALITY FILTER
# ============================================================================

def is_blocked_url(url: str) -> bool:
    """Check if URL matches blocklist patterns."""
    url_lower = url.lower()
    for pattern in URL_BLOCKLIST:
        if pattern in url_lower:
            return True
    return False


# ============================================================================
# FETCHER
# ============================================================================

class Fetcher:
    def __init__(self, config: dict, lookback: timedelta):
        self.config = config
        self.lookback = lookback
        self.cutoff = datetime.now(timezone.utc) - lookback
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "US-Canada-Trade-Digest/2.0 (policy research)"
        })

    def fetch_rss(self, source: dict) -> list[SourceItem]:
        items = []
        try:
            feed = feedparser.parse(
                source.get("rss_url", source["url"]),
                request_headers={"User-Agent": self.session.headers["User-Agent"]},
            )
            for entry in feed.entries:
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

                if pub_date and pub_date < self.cutoff:
                    continue

                snippet = ""
                if hasattr(entry, "summary"):
                    snippet = BeautifulSoup(entry.summary, "html.parser").get_text()[:500]

                url = entry.get("link", source["url"])
                if is_blocked_url(url):
                    continue

                items.append(SourceItem(
                    title=entry.get("title", "Untitled"),
                    url=url,
                    source_name=source["name"],
                    source_category=source.get("_category", "general"),
                    published=pub_date,
                    snippet=snippet,
                ))
        except Exception as e:
            logging.warning(f"RSS fetch failed for {source['name']}: {e}")
        return items

    def fetch_api(self, source: dict) -> list[SourceItem]:
        items = []
        try:
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            api_url = source["api_url"].replace("{yesterday}", yesterday)

            resp = self.session.get(api_url, timeout=self.config["request_timeout"])
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", data if isinstance(data, list) else [])
            for doc in results:
                pub_date = None
                if "publication_date" in doc:
                    pub_date = datetime.strptime(
                        doc["publication_date"], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)

                url = doc.get("html_url", doc.get("url", source["url"]))
                if is_blocked_url(url):
                    continue

                items.append(SourceItem(
                    title=doc.get("title", "Untitled"),
                    url=url,
                    source_name=source["name"],
                    source_category=source.get("_category", "general"),
                    published=pub_date,
                    snippet=doc.get("abstract", doc.get("excerpt", ""))[:500],
                ))
        except Exception as e:
            logging.warning(f"API fetch failed for {source['name']}: {e}")
        return items

    def fetch_web_scrape(self, source: dict) -> list[SourceItem]:
        items = []
        try:
            resp = self.session.get(
                source["url"], timeout=self.config["request_timeout"]
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            selectors = [
                "article", ".news-item", ".press-release",
                ".hearing-item", ".entry", "li.views-row",
                ".post", ".blog-post",
            ]
            elements = []
            for sel in selectors:
                elements.extend(soup.select(sel))

            if not elements:
                elements = soup.find_all("a", href=True)

            for el in elements[:50]:
                title = el.get_text(strip=True)[:200]
                if len(title) < CONFIG["min_title_length"]:  # v2: configurable
                    continue

                link = el.get("href", "")
                if link and not link.startswith("http"):
                    link = urljoin(source["url"], link)

                if is_blocked_url(link):
                    continue

                items.append(SourceItem(
                    title=title,
                    url=link or source["url"],
                    source_name=source["name"],
                    source_category=source.get("_category", "general"),
                    snippet=title,
                ))
        except Exception as e:
            logging.warning(f"Web scrape failed for {source['name']}: {e}")
        return items

    def fetch_source(self, source: dict) -> list[SourceItem]:
        source_type = source.get("type", "web_scrape")
        if source_type == "rss":
            return self.fetch_rss(source)
        elif source_type == "api":
            return self.fetch_api(source)
        else:
            return self.fetch_web_scrape(source)


# ============================================================================
# FILTER & SCORER (v2: with thought leader name matching)
# ============================================================================

class Filter:
    WEIGHTS = {"high": 3, "medium": 2, "low": 1}

    def __init__(self, keywords: dict, source_keywords: list[str] = None):
        self.keywords = keywords
        self.source_keywords = source_keywords or []

    def score_item(self, item: SourceItem) -> SourceItem:
        text = f"{item.title} {item.snippet}".lower()
        score = 0.0
        matched = []

        # Global keyword scoring
        for tier, terms in self.keywords.items():
            weight = self.WEIGHTS[tier]
            for term in terms:
                if term.lower() in text:
                    score += weight
                    matched.append(term)

        # Source-specific keyword boost
        for kw in self.source_keywords:
            if kw.lower() in text:
                score += 1.5
                if kw not in matched:
                    matched.append(kw)

        # v2: Thought leader name matching
        leaders_found = []
        for name in ALL_LEADERS:
            if name.lower() in text:
                weight = LEADER_WEIGHT_MAP.get(name.lower(), 1.5)
                score += weight
                leaders_found.append(name)
                if name not in matched:
                    matched.append(name)

        item.relevance_score = score
        item.keywords_matched = matched
        item.leaders_matched = leaders_found
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
        return [
            i for i in scored
            if i.relevance_score >= min_score
            and len(i.keywords_matched) >= min_keywords
        ]


# ============================================================================
# DEDUPLICATOR
# ============================================================================

class Deduplicator:
    def __init__(self):
        self.seen_hashes = set()
        self.seen_titles = []

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()

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
            self.seen_hashes.add(item.item_hash)
            self.seen_titles.append(self._normalize(item.title))
            unique.append(item)
        return unique


# ============================================================================
# CATEGORIZER (v2: includes thought_leaders section)
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
                      "floor speech", "motion", "amendment", "resolution"],
    },
    "diplomatic": {
        "source_categories": ["us_government", "canadian_government"],
        "keywords": ["bilateral", "summit", "meeting", "negotiation", "ambassador",
                      "diplomatic", "foreign minister", "secretary of state", "statement"],
    },
    "industry_impact": {
        "source_categories": ["industry", "media"],
        "keywords": ["business", "industry", "sector", "manufacturer", "exporter",
                      "supply chain", "auto", "steel", "aluminum", "energy", "agriculture"],
    },
    "analysis": {
        "source_categories": ["think_tanks"],
        "keywords": ["analysis", "paper", "report", "study", "research", "policy",
                      "commentary", "outlook", "forecast", "briefing"],
    },
    "disputes": {
        "source_categories": ["legal"],
        "keywords": ["dispute", "panel", "ruling", "WTO", "appeal", "arbitration",
                      "settlement", "chapter 19", "chapter 31", "compliance"],
    },
    "thought_leaders": {
        "source_categories": ["newsletters", "commentary", "podcasts"],
        "keywords": [],  # Driven by name matching, not keywords
    },
}


def categorize_item(item: SourceItem) -> str:
    """Assign an item to its best-fit digest section.

    v2: Items mentioning 2+ thought leaders, or from newsletter/commentary
    sources with leader mentions, go to thought_leaders section.
    """
    # v2: Route to thought_leaders if strong leader signal
    if len(item.leaders_matched) >= 2:
        return "thought_leaders"
    if (item.source_category in ["newsletters", "commentary", "podcasts"]
            and len(item.leaders_matched) >= 1):
        return "thought_leaders"

    scores = {}
    text = f"{item.title} {item.snippet}".lower()

    for section, rules in SECTION_RULES.items():
        if section == "thought_leaders":
            continue  # handled above
        score = 0
        if item.source_category in rules["source_categories"]:
            score += 2
        for kw in rules["keywords"]:
            if kw in text:
                score += 1
        scores[section] = score

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "analysis"


# ============================================================================
# PUBLISHER
# ============================================================================

SECTION_LABELS = {
    "trade_actions": "⚖️ Trade Actions & Regulations",
    "legislation": "🏛️ Legislation & Hearings",
    "diplomatic": "🤝 Diplomatic Developments",
    "industry_impact": "🏭 Industry Impact",
    "analysis": "📊 Analysis & Commentary",
    "disputes": "⚔️ Disputes & Legal",
    "thought_leaders": "🎙️ Thought Leader Watch",
}


def generate_html_digest(items_by_section: dict, date: str) -> str:
    """Render digest as HTML using Jinja2 template."""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("digest.html")

    joke = random.choice(TRADE_QUIPS)
    total_items = sum(len(v) for v in items_by_section.values())
    source_names = set()
    leaders_today = set()
    for items in items_by_section.values():
        for item in items:
            source_names.add(item.source_name)
            leaders_today.update(item.leaders_matched)

    return template.render(
        date=date,
        joke=joke,
        sections=items_by_section,
        section_labels=SECTION_LABELS,
        total_items=total_items,
        total_sources=len(source_names),
        total_leaders=len(leaders_today),
        leaders_today=sorted(leaders_today),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


def send_email(html: str, subject: str, recipients: list[str]):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        logging.info("SMTP not configured — skipping email delivery")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        logging.info(f"Email sent to {len(recipients)} recipients")
    except Exception as e:
        logging.error(f"Email delivery failed: {e}")


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def load_sources(path: str = None) -> list[dict]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "sources.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    sources = []
    for category, source_list in raw.items():
        for source in source_list:
            source["_category"] = category
            sources.append(source)
    return sources


def run_pipeline(dry_run: bool = False, target_date: Optional[str] = None,
                 section_filter: Optional[str] = None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger("pipeline")

    date_str = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log.info(f"=== US-Canada Trade Policy Digest v2 — {date_str} ===")
    log.info(f"    Tracking {len(ALL_LEADERS)} thought leaders")
    log.info(f"    Min score: {CONFIG['min_relevance_score']}, Min keywords: {CONFIG['min_keywords_matched']}")

    # 1. LOAD
    sources = load_sources()
    log.info(f"Loaded {len(sources)} sources")

    # 2. FETCH
    lookback = timedelta(hours=CONFIG["lookback_hours"])
    fetcher = Fetcher(CONFIG, lookback)
    all_items = []
    for source in sources:
        items = fetcher.fetch_source(source)
        log.info(f"  {source['name']}: {len(items)} items")
        all_items.extend(items)
    log.info(f"Total fetched: {len(all_items)} items")

    # 3. FILTER (v2: stricter thresholds)
    relevant = []
    for source in sources:
        source_items = [i for i in all_items if i.source_name == source["name"]]
        source_filter = Filter(KEYWORDS, source.get("keywords", []))
        relevant.extend(source_filter.filter_items(source_items))
    log.info(f"After keyword filter: {len(relevant)} items")

    # 4. DEDUPLICATE
    deduper = Deduplicator()
    unique = deduper.deduplicate(relevant)
    log.info(f"After dedup: {len(unique)} items")

    # v2: Log leader mentions
    all_leaders_mentioned = set()
    for item in unique:
        all_leaders_mentioned.update(item.leaders_matched)
    if all_leaders_mentioned:
        log.info(f"Leaders mentioned today: {', '.join(sorted(all_leaders_mentioned))}")

    # 5. CATEGORIZE
    for item in unique:
        item.digest_section = categorize_item(item)

    items_by_section = {}
    for section in CONFIG["digest_sections"]:
        section_items = sorted(
            [i for i in unique if i.digest_section == section],
            key=lambda x: x.relevance_score, reverse=True,
        )[:CONFIG["max_items_per_section"]]
        if section_items:
            items_by_section[section] = section_items

    if section_filter:
        items_by_section = {k: v for k, v in items_by_section.items() if k == section_filter}

    total = sum(len(v) for v in items_by_section.values())
    log.info(f"Digest items: {total} across {len(items_by_section)} sections")

    if dry_run:
        log.info("=== DRY RUN ===")
        for section, items in items_by_section.items():
            print(f"\n### {SECTION_LABELS.get(section, section)}")
            for item in items:
                leaders_str = f" | Leaders: {', '.join(item.leaders_matched)}" if item.leaders_matched else ""
                print(f"  [{item.relevance_score:.1f}] {item.title}")
                print(f"         {item.url}")
                print(f"         Keywords: {', '.join(item.keywords_matched[:5])}{leaders_str}")
        return

    # 6. PUBLISH
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    os.makedirs(CONFIG["archive_dir"], exist_ok=True)

    html = generate_html_digest(items_by_section, date_str)

    output_path = os.path.join(CONFIG["output_dir"], "index.html")
    with open(output_path, "w") as f:
        f.write(html)
    log.info(f"HTML saved to {output_path}")

    archive_path = os.path.join(CONFIG["archive_dir"], f"{date_str}.html")
    with open(archive_path, "w") as f:
        f.write(html)

    data_path = os.path.join(CONFIG["archive_dir"], f"{date_str}.json")
    with open(data_path, "w") as f:
        json.dump({
            "date": date_str,
            "leaders_mentioned": sorted(all_leaders_mentioned),
            "sections": {
                section: [asdict(item) for item in items]
                for section, items in items_by_section.items()
            },
        }, f, indent=2, default=str)

    subject = f"🇺🇸🇨🇦 US-Canada Trade Digest — {date_str}"
    if CONFIG["email_recipients"]:
        send_email(html, subject, CONFIG["email_recipients"])

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="US-Canada Trade Policy Daily Digest v2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--section", type=str, default=None, choices=CONFIG["digest_sections"])
    args = parser.parse_args()
    run_pipeline(dry_run=args.dry_run, target_date=args.date, section_filter=args.section)
