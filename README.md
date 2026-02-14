# 🇺🇸🇨🇦 US-Canada Trade Policy Daily Digest v2

Automated daily intelligence gathering on US-Canada trade policy. Inspired by Alexander Panetta's systematic approach to finding Canada-related scoops through US government source monitoring.

## What's New in v2

**🎙️ Thought Leader Watch** — Tracks 100+ named voices across the US-Canada trade policy landscape:
- Government officials (USTR, Global Affairs, ambassadors)
- Congressional/parliamentary figures
- Think tank analysts (C.D. Howe, PIIE, Wilson Center, CSIS)
- Trade lawyers and industry voices
- Key journalists and commentators

**📡 Expanded Sources** — Now monitors 50+ sources including:
- Newsletters (Morning Trade, Paul Wells, Capitolism, C.D. Howe Intelligence Memos)
- Podcasts (Trade Talks, Canusa Street, Herle Burly, Trade Guys)
- Commentary blogs (PIIE Trade Watch, LexSage, CSIS Scholl Chair)

**🔧 Quality Improvements:**
- Minimum relevance score raised from 1.0 → 3.0
- Requires 2+ keyword matches (was 1)
- URL blocklist filters social media, login pages, navigation junk
- Minimum title length raised to 20 characters
- Name-based relevance boost for tracked thought leaders

## Digest Sections

| Section | What It Catches |
|---------|----------------|
| ⚖️ Trade Actions & Regulations | Tariff notices, executive orders, regulatory changes |
| 🏛️ Legislation & Hearings | Bills, committee hearings, floor speeches |
| 🤝 Diplomatic Developments | Bilateral meetings, ambassador statements |
| 🏭 Industry Impact | Business reactions, sector-specific developments |
| 📊 Analysis & Commentary | Think tank reports, policy papers |
| ⚔️ Disputes & Legal | WTO panels, CUSMA dispute proceedings |
| 🎙️ Thought Leader Watch | **NEW** — Key voices weighing in today |

## How It Works

Zero API costs. No AI summarization.

1. **Fetch** — RSS, APIs, and web scraping across 50+ sources
2. **Score** — Weighted keyword taxonomy + thought leader name matching
3. **Filter** — Min score 3.0, min 2 keywords, URL blocklist
4. **Deduplicate** — Hash + Jaccard title similarity
5. **Categorize** — Route to best-fit section (leader mentions → Thought Leader Watch)
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
