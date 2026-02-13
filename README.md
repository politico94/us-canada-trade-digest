# 🇺🇸🇨🇦 US-Canada Trade Policy Daily Digest (Free)

An automated pipeline that monitors 40+ government, legislative, think tank, and media sources for US-Canada trade policy developments. No API keys. No costs. Just fetch, filter, and publish.

## How it works

```
40+ sources → Fetch → Keyword filter → Deduplicate → Categorize → Publish
```

Every morning at 6:30 AM ET, GitHub Actions runs the pipeline for free. It publishes to GitHub Pages — your digest gets its own URL.

**Total cost: $0.**

## What you get

Headlines and links, filtered by relevance and organized into six sections:

| Section | What it covers |
|---------|---------------|
| ⚖️ Trade Actions | Tariffs, duties, regulatory moves, executive orders |
| 🏛️ Legislation | Bills, hearings, committee testimony, Hansard |
| 🤝 Diplomatic | Bilateral meetings, negotiations, statements |
| 🏭 Industry Impact | Business/sector effects, supply chain disruptions |
| 📊 Analysis | Think tank papers, policy commentary |
| ⚔️ Disputes | WTO panels, CUSMA disputes, legal rulings |

Plus a trade policy dad joke.

## Setup (from browser — no terminal needed)

1. **Create a GitHub account** at [github.com](https://github.com) (free)
2. **Create a new repo** at [github.com/new](https://github.com/new) — name it `us-canada-trade-digest`, set to **Public**
3. **Upload files** — click "uploading an existing file", drag in all the files from this folder (including the hidden `.github` folder)
4. **Enable Pages** — go to Settings → Pages → Source: **GitHub Actions**
5. **Run it** — go to Actions tab → "Daily US-Canada Trade Digest" → Run workflow

Your digest will be live at `https://YOUR_USERNAME.github.io/us-canada-trade-digest/`

It runs automatically every morning after that.

## Want AI summaries later?

The paid version adds Claude-powered summaries of each item. To upgrade:
1. Get an API key at [console.anthropic.com](https://console.anthropic.com)
2. Add it as a repo secret called `ANTHROPIC_API_KEY`
3. Swap `pipeline.py` for the paid version

## Customize

**Add sources:** Edit `sources.yaml` — copy any block, change the fields.

**Adjust keywords:** Edit `KEYWORDS` in `pipeline.py`. Three tiers:
- High (3x weight): "CUSMA", "softwood lumber", "retaliatory tariff"
- Medium (2x): "bilateral trade", "auto rules of origin"
- Low (1x): "canada", "tariff", "export"

## Disclaimer

This is not journalism. It's automated keyword filtering — a robot version of checking six websites every morning. All items link to primary sources.
