"""Per-archetype card renderers (PR D-1 + PR D-2 / meta-v8.7.0).

Produces the HTML for the daily hero card. Six archetypes mirror
card_picker.json's cascade outputs (word / paradox / silence / shift /
sources / tilt). Echo is deferred until lag.schema.json + the
cross_outlet_lag writer mature post-merge.

Each renderer takes (today_card, signals) where:
  - today_card is the dict returned by pick_todays_card() carrying
    card_kind / headline / kicker / story_title / score_breakdown /
    see_how_path.
  - signals is the collect_story_signals() output carrying the
    on-disk artifacts (analysis, trajectory, coverage, sources,
    within_lang_llr, tilt_files).

Returns a complete `<article class="card card--<kind>">…</article>`
HTML fragment. The fragment is escaped for safety (html.escape on
every interpolation).
"""
from __future__ import annotations

import html as _html
from datetime import date as _date

from publication.site_config import SITE_BASE


# Bucket → emoji flag. Not exhaustive; unknown buckets render with
# an empty string (the bucket name still carries the visual identity).
BUCKET_FLAGS: dict[str, str] = {
    "italy": "🇮🇹", "germany": "🇩🇪", "spain": "🇪🇸", "france": "🇫🇷",
    "uk": "🇬🇧", "usa": "🇺🇸", "iran_state": "🇮🇷", "iran_opp": "🇮🇷",
    "russia": "🇷🇺", "china": "🇨🇳", "japan": "🇯🇵", "india": "🇮🇳",
    "saudi": "🇸🇦", "qatar": "🇶🇦", "egypt": "🇪🇬", "israel": "🇮🇱",
    "turkey": "🇹🇷", "lebanon": "🇱🇧", "canada": "🇨🇦", "mexico": "🇲🇽",
    "argentina_chile": "🇦🇷", "south_korea": "🇰🇷", "philippines": "🇵🇭",
    "vietnam": "🇻🇳", "ukraine": "🇺🇦", "poland": "🇵🇱",
    "wire_services": "📡", "taiwan_hk": "🇹🇼", "indonesia": "🇮🇩",
    "thailand": "🇹🇭", "australia": "🇦🇺", "south_africa": "🇿🇦",
    "nigeria": "🇳🇬", "brazil": "🇧🇷",
}

# Archetype → eyebrow tagline (top label above the headline).
EYEBROWS: dict[str, str] = {
    "word":    "Same event · different words for it",
    "paradox": "Opposing blocs · same conclusion",
    "silence": "Most buckets covered this · some didn't",
    "shift":   "How the framing moved this week",
    "sources": "Whose voices got platformed",
    "tilt":    "Furthest from the wire baseline",
    "echo":    "Who echoed whom, how late",
}


def _e(s) -> str:
    """HTML-escape a value (None → '')."""
    return _html.escape(str(s)) if s is not None else ""


def _flag(bucket: str) -> str:
    return BUCKET_FLAGS.get(bucket, "")


def _human_date(iso: str | None) -> str:
    try:
        d = _date.fromisoformat(iso or "")
    except (TypeError, ValueError):
        return _e(iso or "")
    return d.strftime("%-d %B %Y")


def _common_header(today_card: dict) -> str:
    iso = today_card.get("date") or ""
    return (
        '<header class="card-brand">'
        '<span class="brand-mark">THE SAME STORY</span>'
        f'<time datetime="{_e(iso)}">{_e(_human_date(iso))}</time>'
        '</header>'
        f'<p class="card-eyebrow">{_e(EYEBROWS.get(today_card.get("card_kind"), ""))}</p>'
        f'<h1 class="card-headline">{_e(today_card.get("headline", ""))}</h1>'
        f'<p class="card-kicker">{_e(today_card.get("kicker", ""))}</p>'
    )


def _common_footer(today_card: dict, byline_text: str) -> str:
    href = today_card.get("see_how_path") or "#"
    return (
        '<footer class="card-byline">'
        f'<span>{_e(byline_text)}</span>'
        f'<a class="see-how" href="{_e(href)}">see how →</a>'
        '</footer>'
    )


def _synthesis_line(today_card: dict, css_class: str) -> str:
    """Render the finding_synthesis as a small line inside card-content.

    Used by archetype renderers that don't already have their own
    archetype-specific synthesis pattern (paradox-synthesis from
    joint_conclusion; shift-synthesis from computed Δshare). Word,
    silence, sources, and tilt cards previously displayed nothing
    here — the machine-generated analytical observation was wasted.
    """
    syn = (today_card.get("finding_synthesis") or "").strip()
    if not syn:
        return ""
    return f'<p class="{_e(css_class)}">{_e(syn)}</p>'


# ---------------------------------------------------------------------------
# Archetype renderers
# ---------------------------------------------------------------------------

def _render_word(today_card: dict, signals: dict) -> str:
    """Word card — top distinctive term per bucket, up to 6 buckets."""
    llr = (signals.get("within_lang_llr") or {}).get("by_bucket") or {}
    rows: list[tuple[str, str, float]] = []  # (bucket, term, llr)
    for bucket, data in llr.items():
        terms = data.get("distinctive_terms") or []
        if not terms:
            continue
        top = terms[0]
        rows.append((bucket, top.get("term", ""), float(top.get("llr", 0))))
    rows.sort(key=lambda r: -r[2])
    rows = rows[:6]
    if not rows:
        body = ('<p class="empty-state">Vocabulary signal is accruing. '
                'Check back in a few days.</p>')
    else:
        word_rows = "".join(
            f'<div class="word-row">'
            f'<span class="flag">{_flag(b)}</span>'
            f'<span class="bucket-name">{_e(b)}</span>'
            f'<span class="word-stack">'
            f'<span class="word">{_e(term)}</span>'
            f'<span class="llr">llr {llr_score:.0f}</span>'
            f'</span>'
            f'</div>'
            for b, term, llr_score in rows
        )
        body = f'<div class="card-content">{word_rows}{_synthesis_line(today_card, "word-synthesis")}</div>'
    byline = f"{len(rows)} bucket{'s' if len(rows) != 1 else ''} · same-language cohorts"
    return f'<article class="card card--word">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


def _render_paradox(today_card: dict, signals: dict) -> str:
    p = (signals.get("analysis") or {}).get("paradox") or {}
    a = p.get("a") or {}
    b = p.get("b") or {}
    joint = p.get("joint_conclusion") or ""
    body = (
        '<div class="card-content">'
        '<div class="paradox-side">'
        f'<blockquote>{_e(a.get("quote", ""))}</blockquote>'
        f'<cite><span class="flag">{_flag(a.get("bucket"))}</span> '
        f'{_e(a.get("outlet", ""))} · {_e(a.get("bucket", ""))}</cite>'
        '</div>'
        '<span class="paradox-connector">both said</span>'
        '<div class="paradox-side">'
        f'<blockquote>{_e(b.get("quote", ""))}</blockquote>'
        f'<cite><span class="flag">{_flag(b.get("bucket"))}</span> '
        f'{_e(b.get("outlet", ""))} · {_e(b.get("bucket", ""))}</cite>'
        '</div>'
        f'<p class="paradox-synthesis">{_e(joint)}</p>'
        '</div>'
    )
    byline = f"{_e(a.get('bucket', '?'))} vs {_e(b.get('bucket', '?'))} · same conclusion"
    return f'<article class="card card--paradox">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


def _render_silence(today_card: dict, signals: dict) -> str:
    story_key = signals.get("story_key")
    non_cov = ((signals.get("coverage") or {}).get("non_coverage") or {}).get(story_key) or {}
    silent = [b for b, info in non_cov.items()
               if isinstance(info, dict) and info.get("state") == "silent"]
    covered = [b for b, info in non_cov.items()
                if isinstance(info, dict) and info.get("state") == "covered"]
    if not silent:
        body = '<div class="card-content"><p class="empty-state">No silences detected today.</p></div>'
    else:
        primary = silent[0]
        # alt story for the silent bucket — peek at non_cov[primary].what_they_covered_instead if present
        alt = (non_cov.get(primary) or {}).get("what_they_covered_instead") or ""
        silent_block = (
            '<div class="silence-absent">'
            f'<span class="flag">{_flag(primary)}</span>'
            f'<span class="silence-label">{_e(primary)} · didn’t cover</span>'
            '</div>'
        )
        replacement = (
            f'<p class="silence-replacement">{_e(alt) if alt else "They ran something else; the story didn’t appear."}</p>'
            if alt or True else ""
        )
        covered_flags = "".join(f'<span class="flag">{_flag(b)}</span>' for b in covered[:14])
        covered_block = (
            '<div class="silence-covered">'
            f'<span class="silence-covered-label">{len(covered)} bucket'
            f"{'s' if len(covered) != 1 else ''} that did cover</span>"
            f'<div class="silence-covered-row">{covered_flags}</div>'
            '</div>'
        )
        body = f'<div class="card-content">{silent_block}<div>{replacement}{covered_block}</div>{_synthesis_line(today_card, "silence-synthesis")}</div>'
    byline = f"{len(covered)} carried · {len(silent)} silent"
    return f'<article class="card card--silence">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


def _render_shift(today_card: dict, signals: dict) -> str:
    traj = (signals.get("trajectory") or {}).get("frame_trajectories") or {}
    # Find the frame with the biggest swing in the last 7 days
    best = None  # (frame_id, entries_window)
    best_delta = 0.0
    for fid, entries in traj.items():
        window = (entries or [])[-7:]
        for e in window:
            d = e.get("delta_share")
            if d is None:
                continue
            if abs(d) > best_delta:
                best_delta = abs(d)
                best = (fid, window)
    if not best:
        body = '<div class="card-content"><p class="empty-state">Frame-share movement still accruing.</p></div>'
        byline = "trajectory data accruing"
    else:
        fid, window = best
        rows = "".join(
            '<li class="' + ("changed" if abs(e.get("delta_share") or 0) > 0.10 else "") + '">'
            f'<span class="day">{_e((e.get("date") or "")[5:])}</span>'
            f'<span class="frame">{e.get("share", 0):.0%}</span>'
            '</li>'
            for e in window
        )
        body = (
            '<div class="card-content">'
            f'<ol class="shift-sequence">{rows}</ol>'
            f'<p class="shift-synthesis">{_e(fid)} share moved {best_delta * 100:.0f}pp across the window.</p>'
            '</div>'
        )
        byline = f"{len(window)} day{'s' if len(window) != 1 else ''} · {_e(fid)}"
    return f'<article class="card card--shift">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


def _render_sources(today_card: dict, signals: dict) -> str:
    sd = (signals.get("sources") or {}).get("sources") or []
    if not sd:
        body = '<div class="card-content"><p class="empty-state">Source-attribution data accruing.</p></div>'
        byline = "sources accruing"
    else:
        # Group by speaker_affiliation_bucket; count each.
        from collections import Counter
        counts: Counter[str] = Counter(s.get("speaker_affiliation_bucket") or "unknown" for s in sd)
        total = sum(counts.values()) or 1
        # Determine top outlet's perspective if cleanly identifiable.
        outlets = Counter(s.get("outlet") or "?" for s in sd)
        top_outlet, _ = outlets.most_common(1)[0]
        rows = "".join(
            '<li>'
            f'<span class="speaker-type">{_e(stype.replace("_", " ").title())}</span>'
            f'<span class="speaker-bar"><span style="width:{100 * c / total:.0f}%"></span></span>'
            f'<span class="speaker-count">{c}</span>'
            '</li>'
            for stype, c in counts.most_common()
        )
        body = (
            '<div class="card-content">'
            '<div class="sources-outlet">'
            '<div class="sources-outlet-head">'
            f'<span class="sources-outlet-name">{_e(top_outlet)}</span>'
            f'<span class="sources-outlet-meta">{len(sd)} voices · {len(counts)} affiliation types</span>'
            '</div>'
            f'<ol class="sources-breakdown">{rows}</ol>'
            '</div>'
            f'{_synthesis_line(today_card, "sources-synthesis")}'
            '</div>'
        )
        distinct_buckets = len({s.get("bucket") for s in sd if s.get("bucket")})
        byline = f"{len(sd)} speakers · {distinct_buckets} buckets · {len(counts)} affiliation types"
    return f'<article class="card card--sources">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


def _render_tilt(today_card: dict, signals: dict) -> str:
    tilt_files = signals.get("tilt_files") or []
    rows: list[tuple[str, str, float, float]] = []  # (bucket, outlet, z_wire, z_mean)
    for tilt in tilt_files:
        anchors = tilt.get("anchors") or {}
        wire = (anchors.get("wire") or {}).get("positive_tilt") or []
        mean = (anchors.get("bucket_mean") or {}).get("positive_tilt") or []
        z_wire = float(wire[0].get("z_score", 0)) if wire else 0.0
        z_mean = float(mean[0].get("z_score", 0)) if mean else 0.0
        rows.append((tilt.get("bucket", "?"), tilt.get("outlet", "?"), z_wire, z_mean))
    rows.sort(key=lambda r: -r[2])
    rows = rows[:5]
    if not rows:
        body = '<div class="card-content"><p class="empty-state">Per-outlet tilt accruing.</p></div>'
        byline = "tilt accruing"
    else:
        items = "".join(
            '<li class="tilt-row' + (' featured' if i == 0 else '') + '">'
            f'<span class="flag">{_flag(bucket)}</span>'
            f'<span class="tilt-outlet">{_e(outlet)}</span>'
            '<span class="tilt-scores">'
            f'<span class="tilt-score">+{z_wire:.1f}<em>vs wire</em></span>'
            f'<span class="tilt-score">+{z_mean:.1f}<em>vs cross-bucket</em></span>'
            '</span>'
            '</li>'
            for i, (bucket, outlet, z_wire, z_mean) in enumerate(rows)
        )
        body = f'<div class="card-content"><ol class="tilt-stack">{items}</ol>{_synthesis_line(today_card, "tilt-synthesis")}</div>'
        byline = f"{len(rows)} outlets · two anchors"
    return f'<article class="card card--tilt">{_common_header(today_card)}{body}{_common_footer(today_card, byline)}</article>'


# ---------------------------------------------------------------------------
# Top-level render entry points
# ---------------------------------------------------------------------------

RENDERERS: dict = {
    "word": _render_word,
    "paradox": _render_paradox,
    "silence": _render_silence,
    "shift": _render_shift,
    "sources": _render_sources,
    "tilt": _render_tilt,
}


def render_card_html(today_card: dict, signals: dict) -> str:
    """Dispatch on card_kind; render the daily hero card."""
    kind = today_card.get("card_kind") or "word"
    return RENDERERS.get(kind, _render_word)(today_card, signals)


def render_today_strip(other_stories: list[dict]) -> str:
    """Render the "Also today" strip — small tiles for the stories
    that didn't win the daily-card slot. `other_stories` is a list of
    dicts with story_key / title / card_kind / finding_synthesis /
    event_summary fields (typically taken from the per-date index)."""
    if not other_stories:
        return ""
    items = "".join(
        f'<li><a href="{SITE_BASE}/{_e(date)}/{_e(s["key"])}/">'
        f'<span class="today-kind">{_e((s.get("card_kind") or "word").title())}</span>'
        f'<p class="today-headline">{_e(s.get("event_summary") or s.get("title", ""))}</p>'
        f'<p class="today-finding">{_e(s.get("finding_synthesis", ""))}</p>'
        '</a></li>'
        for s in other_stories
        for date in [s.get("date", "")]
    )
    return (
        '<section class="site-aux">'
        '<div class="today-strip">'
        '<h2>Also today</h2>'
        f'<ol>{items}</ol>'
        '</div>'
        '</section>'
    )


def render_index_html(today_card: dict, signals: dict,
                       other_stories: list[dict], archive_dates: list[str]) -> str:
    """Produce the full home page. Wraps the rendered hero card +
    today-strip + 5-day archive in the site shell from
    web/index.html. The shell's <head> + actions + footer markup are
    inlined here so the renderer is the single source of truth for
    the home page."""
    card_html = render_card_html(today_card, signals)
    strip_html = render_today_strip(other_stories)
    archive_html = ""
    if archive_dates:
        archive_html = (
            '<section class="archive">'
            '<h2>This week</h2>'
            '<ul class="archive-list">'
            + "".join(f'<li><a href="{SITE_BASE}/{_e(d)}/">{_e(_human_date(d))}</a></li>'
                       for d in archive_dates)
            + '</ul></section>'
        )
    iso = today_card.get("date") or ""
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Same Story · {_e(_human_date(iso))}</title>
  <meta property="og:title" content="{_e(today_card.get("headline", "The Same Story"))}">
  <meta property="og:description" content="{_e(today_card.get("kicker", ""))}">
  <meta property="og:image" content="{SITE_BASE}/today.png">
  <link rel="stylesheet" href="{SITE_BASE}/styles.css">
</head>
<body>
<main class="hero">
  {card_html}
  <div class="card-actions">
    <button type="button" data-action="share">Share</button>
    <button type="button" data-action="copy-link">Copy link</button>
    <a href="{SITE_BASE}/today.png" download>Download image</a>
  </div>
</main>
{strip_html}
{archive_html}
<footer class="site-footer">
  <a href="{SITE_BASE}/methodology/">methodology</a>
  <a href="{SITE_BASE}/archive/">archive</a>
  <a href="{SITE_BASE}/corrections.html">corrections</a>
  <span>meta · v{_e(today_card.get("meta_version", ""))}</span>
</footer>
<script src="{SITE_BASE}/app.js" defer></script>
</body>
</html>
'''


# ---------------------------------------------------------------------------
# PR D-2: Playwright PNG renderer
# ---------------------------------------------------------------------------

# Viewport sizes for the og:image / social-share outputs. The native
# card aspect (1200×675) matches the design; 1200×630 is the Twitter
# card spec; 1080×1920 is Instagram Story 9:16.
PNG_VIEWPORTS: dict[str, tuple[int, int]] = {
    "today":         (1200, 675),
    "today-twitter": (1200, 630),
    "today-story":   (1080, 1920),
}


def _png_wrapper_html(card_html: str, styles_css_text: str,
                       viewport_w: int, viewport_h: int) -> str:
    """A self-contained HTML doc that embeds the card + the site CSS
    inline. Inlining the CSS rather than linking it means Playwright
    can render against a `data:` URL with no external fetches —
    deterministic and offline-capable. The body is forced to
    viewport dimensions so the card fills the PNG frame."""
    return f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<style>{styles_css_text}
html, body {{ margin: 0; padding: 0; width: {viewport_w}px; height: {viewport_h}px; overflow: hidden; }}
body {{ display: flex; align-items: center; justify-content: center; }}
.card {{ width: 100% !important; max-width: {viewport_w}px !important;
         height: 100%; max-height: {viewport_h}px;
         box-shadow: none !important; border-radius: 0 !important; }}
</style></head><body>{card_html}</body></html>'''


def render_card_png(card_html: str, styles_css_text: str,
                     viewport: str = "today") -> bytes:
    """Render the given card HTML to a PNG at the named viewport size.
    Raises RuntimeError if playwright isn't installed or chromium
    isn't downloaded — the caller (build_index) should treat this as
    "skip PNG generation, fall back to og:image text-only" rather
    than fail the publish step.

    `card_html` is the <article class="card card--<kind>">…</article>
    fragment produced by render_card_html. `styles_css_text` is the
    full content of web/styles.css (inlined so Playwright doesn't
    need to fetch over the network).
    """
    if viewport not in PNG_VIEWPORTS:
        raise ValueError(f"unknown viewport {viewport!r}; valid: {list(PNG_VIEWPORTS)}")
    w, h = PNG_VIEWPORTS[viewport]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(f"playwright not installed: {e}") from e

    doc = _png_wrapper_html(card_html, styles_css_text, w, h)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": w, "height": h},
                                            device_scale_factor=2)
            page = context.new_page()
            page.set_content(doc, wait_until="networkidle")
            buf = page.screenshot(type="png", full_page=False, omit_background=False)
        finally:
            browser.close()
    return buf

