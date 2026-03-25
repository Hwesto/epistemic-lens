# Epistemic Lens v0.2

Cross-national news comparison using multilingual embeddings. No translation needed.

## What it does

1. Pulls RSS feeds from ~40 outlets in 15 countries (Farsi, Mandarin, Arabic, Hebrew, Russian, Turkish, Hindi, Portuguese, Japanese, French, English)
2. Embeds all articles into shared vector space using `paraphrase-multilingual-MiniLM-L12-v2`
3. Auto-clusters articles by topic across languages
4. Scores convergence (adversarial agreement = likely facts)
5. Computes newspaper similarity matrix (who echoes whom)
6. Generates a Claude-ready analysis prompt

## Daily output (in snapshots/)

- `YYYY-MM-DD.json` — raw headlines from all feeds
- `YYYY-MM-DD_convergence.json` — topic clusters with cross-source scoring
- `YYYY-MM-DD_similarity.json` — newspaper-to-newspaper similarity matrix
- `YYYY-MM-DD_prompt.md` — paste this into Claude for analysis

## Setup

```bash
pip install -r requirements.txt
python ingest.py
```

First run downloads the 500MB model. Cached after that.

## Countries

| Region | Outlets | Languages |
|--------|---------|-----------|
| Iran (state) | Press TV, IRNA, Fars News, Tehran Times | en, fa |
| Iran (opposition) | Iran International, Radio Farda | en, fa |
| USA | CNN, Fox News, NPR | en |
| UK | BBC, Guardian, Telegraph | en |
| Qatar | Al Jazeera (English + Arabic) | en, ar |
| China | CGTN, Xinhua (en + zh), Global Times | en, zh |
| Russia | TASS (en + ru), RT, Moscow Times | en, ru |
| India | TOI, NDTV, Republic, Dainik Bhaskar | en, hi |
| Israel | Haaretz, JPost, TOI, Ynet Hebrew | en, he |
| Turkey | Daily Sabah, Hurriyet, Ahval | en, tr |
| Saudi Arabia | Arab News, Al Arabiya | en |
| South Korea | Yonhap, Korea Herald | en |
| Japan | NHK, Japan Times | ja, en |
| Brazil | Folha, O Globo | pt |
| Nigeria | Punch, Vanguard | en |
| Wire services | Reuters, AP, AFP/France24 | en, fr |

## The principle

The propaganda is the data. Nothing is filtered or rated.
Convergence across adversarial sources = closest thing to truth.
Divergence on the same story = framing/spin.
Absence from a story = editorial control.
