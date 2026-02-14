# 🇺🇸🇨🇦 US-Canada Trade Policy Daily Digest v3

Automated daily intelligence digest monitoring US-Canada trade policy developments.

## What's New in v3 (Audit Fixes)

**Relevance filtering overhaul:**
- **Co-occurrence requirement:** Leader names only boost score when trade keywords also appear in the same item. This prevents off-topic stories (vigils, election law violations) from appearing just because a tracked person is mentioned.
- **Last-name partial matching removed:** "Ford", "Moe", "Smith" no longer trigger false positives.
- **Trade keyword minimum:** Items must match 2+ actual trade keywords (leader names don't count toward this).

**Source quality fixes:**
- **Landing page detection:** Program homepages (Wilson Center `/program/`, CSIS `/programs/`) are now filtered out unless the URL contains article-pattern indicators (`/analysis/`, `/blog/`, date slugs, etc.).
- **URL base deduplication:** Same URL can't appear twice even with different query params.
- **Undated item score cap:** Items without a parseable date are capped at 4.0 relevance — they can still appear but won't dominate.

**Template improvements:**
- **Removed quip/joke feature** — replaced with factual summary line.
- **Voices banner renamed** to "Mentioned in Trade Context Today" — accurately describes what it shows.
- **Date stamps on all items** where available; items without dates show source only.

## Architecture

1. **Fetch** — RSS + web scraping across 68 sources
2. **Score** — Weighted keyword taxonomy + co-occurrence leader matching
3. **Filter** — Min score 3.0, min 2 trade keywords, URL + landing page blocklist
4. **Deduplicate** — Hash + Jaccard title similarity + URL dedup
5. **Categorize** — Route to best-fit section
6. **Publish** — HTML digest to GitHub Pages, daily archive

## Deployment

Runs via GitHub Actions at 6:30 AM ET daily. Published to GitHub Pages.

```bash
# Local test
pip install -r requirements.txt
python pipeline.py --dry-run

# Full run
python pipeline.py
```

## Live

📰 **[politico94.github.io/us-canada-trade-digest](https://politico94.github.io/us-canada-trade-digest)**
