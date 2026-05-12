"""publication/page_renderers.py — page-level composers (Plan 2: depth-of-data expansion).

The card_renderers.py module produces individual `<article class="card">`
fragments for the daily hero card. This module produces FULL HTML PAGES
for the depth surface that lives one click below the home page.

Five view types:

1. render_story_page(date, story_key, signals, analysis, story_entry)
   → multi-card stack: every archetype with signal for one story.
2. render_coverage_page(date, coverage, story_index)
   → today's 4-state matrix: stories × buckets.
3. render_outlet_page(bucket, outlet, tilt_data)
   → one outlet's tilt fingerprint (108 auto-generated pages).
4. render_methodology_page(meta_dict, codebook, prompt_md, picker_configs)
   → today's pin + 15-frame codebook + analysis prompt + picker explanation.
5. render_archive_page(date_index_pairs)
   → chronological table of every published date.

Plus the small section-renderer helpers (frames matrix, isolation panel,
exclusive-vocab grid, long-form `<details>`) used by the story page.

Per-story page composes the existing `_render_<kind>` archetype functions
unchanged — each wrapped in `<section class="story-section">` whose CSS
hides the card's H1 / eyebrow / kicker / brand-strip (the section header
above provides those). No refactor to card_renderers.py.
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import date as _date
from pathlib import Path

import meta
from publication.card_renderers import (
    BUCKET_FLAGS, EYEBROWS, _e, _flag, _human_date,
    _render_word, _render_paradox, _render_silence,
    _render_shift, _render_sources, _render_tilt,
)
from publication.site_config import SITE_BASE


# Archetype → section heading tagline pair (shown above each per-story card).
SECTION_HEADINGS: dict[str, tuple[str, str]] = {
    "paradox": ("Paradox", "Opposing blocs, same conclusion"),
    "silence": ("Silence", "Who didn’t cover this"),
    "word":    ("Word",    "Same event, different words for it"),
    "shift":   ("Shift",   "How the framing moved"),
    "sources": ("Sources", "Whose voices got platformed"),
    "tilt":    ("Tilt",    "Furthest from the wire baseline"),
}


# ---------------------------------------------------------------------------
# Section-level helpers used by the per-story page
# ---------------------------------------------------------------------------

def _wrap_section(kind: str, card_html: str, caption: str = "") -> str:
    """Wrap an archetype card in `<section class="story-section">` with an
    H2 heading + optional caption (the finding_synthesis). The CSS for
    .story-section > article.card hides the per-card brand/H1/kicker — the
    section heading is the H1's stand-in here."""
    h2, tagline = SECTION_HEADINGS.get(kind, (kind.title(), ""))
    cap_html = f'<p class="story-section-caption">{_e(caption)}</p>' if caption else ""
    return (
        f'<section class="story-section story-section--{_e(kind)}">'
        f'<header class="story-section-head">'
        f'<h2>{_e(h2)} <span class="story-section-tagline">· {_e(tagline)}</span></h2>'
        f'{cap_html}'
        f'</header>'
        f'{card_html}'
        f'</section>'
    )


def _archetypes_with_signal(signals: dict) -> list[str]:
    """Return the list of archetypes that have meaningful data for this
    story, in display order. Always returns word at minimum (renderer
    handles empty state)."""
    out: list[str] = []
    a = signals.get("analysis") or {}
    if a.get("paradox") and (a["paradox"].get("joint_conclusion") or ""):
        out.append("paradox")
    coverage = signals.get("coverage") or {}
    non_cov = (coverage.get("non_coverage") or {}).get(signals.get("story_key")) or {}
    if any(isinstance(v, dict) and v.get("state") == "silent" for v in non_cov.values()):
        out.append("silence")
    llr = (signals.get("within_lang_llr") or {}).get("by_bucket") or {}
    if llr:
        out.append("word")
    if signals.get("tilt_files"):
        out.append("tilt")
    sd = (signals.get("sources") or {}).get("sources") or []
    if len(sd) >= 3:
        out.append("sources")
    traj = (signals.get("trajectory") or {}).get("frame_trajectories") or {}
    has_shift = any(
        any((e.get("delta_share") or 0) and abs(e["delta_share"]) > 0.10 for e in (entries or [])[-7:])
        for entries in traj.values()
    )
    if has_shift:
        out.append("shift")
    # Word fallback if no other signal — already handled above when llr exists.
    if not out:
        out.append("word")
    return out


def render_frames_matrix(analysis: dict) -> str:
    """Compact HTML table: rows = frames detected, cols = buckets carrying.
    Cell `title` attribute = the evidence quote when available."""
    frames = analysis.get("frames") or []
    if not frames:
        return ""
    # Collect every bucket that appears in any frame's buckets[].
    all_buckets: list[str] = []
    for f in frames:
        for b in f.get("buckets") or []:
            if b not in all_buckets:
                all_buckets.append(b)
    all_buckets.sort()
    head_cells = "".join(
        f'<th><span class="bucket-name">{_flag(b)} {_e(b)}</span></th>'
        for b in all_buckets
    )
    rows: list[str] = []
    for f in frames:
        fid = _e(f.get("frame_id") or "?")
        sub = _e(f.get("sub_frame") or "")
        # Map bucket → first evidence quote (for tooltip).
        quote_by_bucket: dict[str, str] = {}
        for ev in f.get("evidence") or []:
            b = ev.get("bucket")
            if b and b not in quote_by_bucket:
                quote_by_bucket[b] = ev.get("quote") or ""
        frame_buckets = set(f.get("buckets") or [])
        cells = "".join(
            (f'<td class="carried" title="{_e(quote_by_bucket.get(b, "")[:200])}">✓</td>'
             if b in frame_buckets else '<td></td>')
            for b in all_buckets
        )
        sub_html = f' <span class="sub-frame">— {sub}</span>' if sub else ""
        rows.append(
            f'<tr><th class="frame-id">{fid}{sub_html}</th>{cells}</tr>'
        )
    return (
        '<table class="frames-matrix">'
        f'<thead><tr><th></th>{head_cells}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )


def render_isolation_panel(metrics: dict) -> str:
    """Horizontal bar chart (pure CSS): buckets sorted by mean_similarity
    ascending. Lower similarity = more isolated/distinctive bucket."""
    isolation = metrics.get("isolation") or []
    if not isolation:
        return ""
    rows = sorted(isolation, key=lambda r: float(r.get("mean_similarity") or 1.0))
    # Bar width = (1 - mean_similarity) * 100 — most isolated has longest bar.
    items = "".join(
        f'<div class="isolation-row">'
        f'<span class="isolation-bucket">{_flag(r.get("bucket"))} {_e(r.get("bucket"))}</span>'
        f'<span class="isolation-bar-wrap">'
        f'<span class="isolation-bar" style="width: {(1 - float(r.get("mean_similarity") or 1.0)) * 100:.1f}%"></span>'
        f'</span>'
        f'<span class="isolation-score">{float(r.get("mean_similarity") or 0):.2f}</span>'
        f'</div>'
        for r in rows
    )
    return (
        '<div class="isolation-panel">'
        '<div class="isolation-legend">bucket · distinctiveness (1 − mean LaBSE similarity) · score</div>'
        f'{items}'
        '</div>'
    )


def render_exclusive_vocab(analysis: dict) -> str:
    """Grid of small per-bucket tiles showing distinctive vocabulary with
    the analyzer's interpretation ('what_it_reveals')."""
    highlights = analysis.get("exclusive_vocab_highlights") or []
    if not highlights:
        return ""
    tiles = "".join(
        f'<div class="exclusive-vocab-tile">'
        f'<div class="exclusive-vocab-head">{_flag(h.get("bucket"))} <strong>{_e(h.get("bucket"))}</strong></div>'
        f'<div class="exclusive-vocab-terms">{", ".join(_e(t) for t in (h.get("terms") or []))}</div>'
        f'<div class="exclusive-vocab-reveals">{_e(h.get("what_it_reveals") or "")}</div>'
        f'</div>'
        for h in highlights
    )
    return f'<div class="exclusive-vocab-grid">{tiles}</div>'


def render_long_form_details(long_draft: dict | None) -> str:
    """Render the LLM-generated long-form draft as a collapsible `<details>`
    block. Body_md is markdown; we convert minimally (paragraphs,
    blockquotes, inline links, basic emphasis). Falls back to empty
    string if no draft."""
    if not long_draft:
        return ""
    body_md = (long_draft.get("body_md") or "").strip()
    if not body_md:
        return ""
    title = _e(long_draft.get("title") or "")
    subtitle = _e(long_draft.get("subtitle") or "")
    body_html = _markdown_to_html(body_md)
    sources = long_draft.get("sources") or []
    src_list = "".join(
        f'<li><a href="{_e(s.get("url"))}" rel="noopener">{_e(s.get("outlet") or s.get("bucket"))}</a> '
        f'<span class="src-bucket">{_e(s.get("bucket"))}</span></li>'
        for s in sources
    )
    sources_block = (
        f'<aside class="long-form-sources"><h4>Sources</h4><ol>{src_list}</ol></aside>'
        if src_list else ""
    )
    subtitle_block = f'<p class="long-form-subtitle">{subtitle}</p>' if subtitle else ""
    meta_line = (
        f'<p class="long-form-meta">'
        f'generated {_e(long_draft.get("generated_at") or "")} · '
        f'model {_e(long_draft.get("model") or "")} · '
        f'meta v{_e(long_draft.get("meta_version") or "")}'
        f'</p>'
    )
    return (
        '<details class="long-form-details">'
        '<summary>Read the full essay <span class="long-form-hint">(LLM-drafted, 600–900 words)</span></summary>'
        '<div class="long-form-body">'
        f'<h3>{title}</h3>'
        f'{subtitle_block}'
        f'{body_html}'
        f'{sources_block}'
        f'{meta_line}'
        '</div>'
        '</details>'
    )


def _markdown_to_html(md: str) -> str:
    """Minimal markdown → HTML for the prose body of long-form drafts.

    Handles: paragraphs (double-newline), blockquotes (line starts with > ),
    inline `[text](url)` links, **bold**, *italic*. Anything else is
    pass-through (escaped). The draft_long.md prompt enforces conservative
    markdown so this covers what we actually see in practice.
    """
    out: list[str] = []
    blocks = re.split(r"\n\s*\n", md.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("> "):
            # Blockquote — strip leading "> " on each line, escape, wrap.
            lines = [_e(re.sub(r"^>\s?", "", ln)) for ln in block.split("\n")]
            inner = " ".join(lines)
            inner = _md_inline(inner)
            out.append(f'<blockquote>{inner}</blockquote>')
        else:
            inner = _e(block).replace("\n", " ")
            inner = _md_inline(inner)
            out.append(f'<p>{inner}</p>')
    return "".join(out)


def _md_inline(s: str) -> str:
    """Apply inline markdown patterns to an already-escaped string.

    Order matters: links first (so their content isn't matched by emphasis),
    then bold, then italic.
    """
    # Links: [text](url) — text is already escaped; url too. Strip in_text.
    def _link(m: "re.Match[str]") -> str:
        txt, url = m.group(1), m.group(2)
        return f'<a href="{url}" rel="noopener">{txt}</a>'
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _link, s)
    # Bold: **text**
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    # Italic: *text* — careful not to match inside **bold**
    s = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', s)
    return s


# ---------------------------------------------------------------------------
# View 1: per-story page
# ---------------------------------------------------------------------------

def render_story_page(date: str, story_key: str, signals: dict,
                       story_entry: dict, long_draft: dict | None = None) -> str:
    """Compose the full /<date>/<story>/ page HTML.

    `story_entry` is the per-story dict from api/<date>/index.json (carries
    title, n_buckets, n_articles, card_kind, event_summary,
    finding_synthesis, top_isolation_bucket).
    """
    analysis = signals.get("analysis") or {}
    metrics = signals.get("metrics") if isinstance(signals.get("metrics"), dict) else _load_metrics_for_story(date, story_key)
    story_title = story_entry.get("title") or story_key
    event_summary = story_entry.get("event_summary") or analysis.get("event_summary") or analysis.get("tldr") or ""
    n_buckets = story_entry.get("n_buckets") or analysis.get("n_buckets") or 0
    n_articles = story_entry.get("n_articles") or analysis.get("n_articles") or 0

    # Hero strip
    hero = (
        '<header class="story-hero">'
        '<p class="story-hero-eyebrow">THE SAME STORY · per-story view</p>'
        f'<h1 class="story-hero-title">{_e(story_title)}</h1>'
        f'<p class="story-hero-kicker">{_e(event_summary)}</p>'
        f'<p class="story-hero-meta">'
        f'<time datetime="{_e(date)}">{_e(_human_date(date))}</time>'
        f' · <span>{n_buckets} buckets</span>'
        f' · <span>{n_articles} articles</span>'
        '</p>'
        '</header>'
    )

    # Sections: every archetype with signal gets its existing card render,
    # wrapped in a story-section that hides the card's brand/H1/kicker.
    sections: list[str] = []
    today_card_for_synthesis = {
        "card_kind": "",  # ignored by renderers for the brand strip we'll hide
        "date": date,
        "story_key": story_key,
        "story_title": story_title,
        "headline": "",      # hidden via CSS
        "kicker": "",        # hidden via CSS
        "see_how_path": "",  # not used in per-story context (no see-how)
        "meta_version": story_entry.get("meta_version") or meta.VERSION,
        "finding_synthesis": "",  # section caption fills this role; no inline line
    }
    from publication.card_renderers import RENDERERS as _RENDERERS
    for kind in _archetypes_with_signal(signals):
        renderer = _RENDERERS.get(kind)
        if not renderer:
            continue
        tc = dict(today_card_for_synthesis, card_kind=kind)
        card_html = renderer(tc, signals)
        # Use card's finding_synthesis as the section caption.
        from publication.build_index import compute_finding_synthesis
        try:
            caption = compute_finding_synthesis(signals, kind)
        except Exception:
            caption = ""
        sections.append(_wrap_section(kind, card_html, caption))

    # Frames matrix — analytical fingerprint
    frames_section = ""
    if analysis.get("frames"):
        frames_section = (
            '<section class="story-section story-section--frames">'
            '<header class="story-section-head">'
            '<h2>Frames <span class="story-section-tagline">· what frames carried this</span></h2>'
            '</header>'
            f'{render_frames_matrix(analysis)}'
            '</section>'
        )

    # Isolation panel — bucket distinctiveness
    isolation_section = ""
    if metrics and metrics.get("isolation"):
        isolation_section = (
            '<section class="story-section story-section--isolation">'
            '<header class="story-section-head">'
            '<h2>Isolation <span class="story-section-tagline">· bucket distinctiveness (LaBSE)</span></h2>'
            '</header>'
            f'{render_isolation_panel(metrics)}'
            '</section>'
        )

    # Exclusive vocab tiles
    vocab_section = ""
    if analysis.get("exclusive_vocab_highlights"):
        vocab_section = (
            '<section class="story-section story-section--vocab">'
            '<header class="story-section-head">'
            '<h2>Distinctive vocabulary <span class="story-section-tagline">· bucket-exclusive terms</span></h2>'
            '</header>'
            f'{render_exclusive_vocab(analysis)}'
            '</section>'
        )

    # Long-form `<details>`
    long_form = render_long_form_details(long_draft)
    long_form_section = (
        f'<section class="story-section story-section--longform">{long_form}</section>'
        if long_form else ""
    )

    # Bottom-line + meta footer
    bottom_line = analysis.get("bottom_line") or ""
    bottom_section = (
        '<section class="story-section story-section--bottom">'
        f'<blockquote class="story-bottom-line">{_e(bottom_line)}</blockquote>'
        '</section>'
        if bottom_line else ""
    )

    raw_links = (
        '<footer class="story-page-footer">'
        f'<p class="story-page-meta">'
        f'generated {_e(analysis.get("generated_at") or "")} · '
        f'model {_e(analysis.get("model") or "")} · '
        f'meta v{_e(analysis.get("meta_version") or "")}'
        '</p>'
        '<p class="story-page-rawlinks">Raw artifacts: '
        f'<a href="briefing.json">briefing.json</a> · '
        f'<a href="metrics.json">metrics.json</a> · '
        f'<a href="analysis.json">analysis.json</a> · '
        f'<a href="sources.json">sources.json</a> · '
        f'<a href="within_lang_llr.json">llr</a> · '
        f'<a href="within_lang_pmi.json">pmi</a>'
        '</p>'
        f'<p class="story-page-back"><a href="{SITE_BASE}/">← back to today</a></p>'
        '</footer>'
    )

    body = hero + "".join(sections) + frames_section + isolation_section + vocab_section + long_form_section + bottom_section + raw_links

    return _wrap_html_document(
        title=f"{story_title} · The Same Story",
        og_title=story_title,
        og_description=event_summary,
        body_class="story-page-body",
        main_class="story-page",
        main_content=body,
    )


def _load_metrics_for_story(date: str, story_key: str) -> dict | None:
    """Sibling-load metrics.json for the story (not in signals from
    collect_story_signals — that one loads everything except metrics)."""
    p = meta.REPO_ROOT / "briefings" / f"{date}_{story_key}_metrics.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# View 2: today's coverage matrix
# ---------------------------------------------------------------------------

def render_coverage_page(date: str, coverage: dict, story_entries: list[dict]) -> str:
    """A single dense 2D table: stories × buckets. Cell state derived from
    coverage[story_key][] feed entries (covered if any n_matching > 0)."""
    # Map story_key → title.
    story_title = {e["key"]: e.get("title", e["key"]) for e in story_entries}
    cov = coverage.get("coverage") or {}
    feeds = coverage.get("feeds") or []
    # Bucket order = unique buckets in feeds[], alphabetical.
    buckets = sorted({f.get("bucket") for f in feeds if f.get("bucket")})

    def _cell_state(story_key: str, bucket: str) -> tuple[str, str]:
        """Return (state, title_text) for one (story, bucket) cell."""
        story_cov = cov.get(story_key) or []
        bucket_records = [r for r in story_cov if r.get("bucket") == bucket]
        if not bucket_records:
            return "dark", f"{bucket}: no feeds matched"
        any_matching = sum(int(r.get("n_matching") or 0) for r in bucket_records)
        any_errored = any(
            (r.get("first_match_extraction_status") or "") in ("ERROR", "DENIED")
            for r in bucket_records
        )
        if any_matching > 0:
            top = max(bucket_records, key=lambda r: int(r.get("n_matching") or 0))
            title = f"{_e(top.get('feed_name') or '?')} — {_e((top.get('first_match_title') or '')[:80])}"
            return "covered", title
        if any_errored:
            return "errored", f"{bucket}: extraction errored"
        return "silent", f"{bucket}: no articles matched"

    # Build the table HTML.
    head_cells = "".join(
        f'<th class="cov-bucket-header"><span>{_flag(b)} {_e(b)}</span></th>'
        for b in buckets
    )
    rows: list[str] = []
    state_counts: dict[str, int] = {"covered": 0, "silent": 0, "errored": 0, "dark": 0}
    for sk in sorted(cov.keys()):
        cells: list[str] = []
        for b in buckets:
            state, title = _cell_state(sk, b)
            state_counts[state] += 1
            symbol = {"covered": "●", "silent": "○", "errored": "⊘", "dark": "▪"}[state]
            cells.append(f'<td class="cov-cell cov-{state}" title="{title}">{symbol}</td>')
        rows.append(
            f'<tr><th class="cov-story-header"><a href="{SITE_BASE}/{_e(date)}/{_e(sk)}/">{_e(story_title.get(sk, sk))}</a></th>'
            f'{"".join(cells)}</tr>'
        )

    table_html = (
        '<table class="coverage-matrix">'
        f'<thead><tr><th class="cov-corner"></th>{head_cells}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )
    legend_html = (
        '<ul class="coverage-legend">'
        f'<li><span class="cov-symbol cov-covered">●</span> covered ({state_counts["covered"]})</li>'
        f'<li><span class="cov-symbol cov-silent">○</span> silent ({state_counts["silent"]})</li>'
        f'<li><span class="cov-symbol cov-errored">⊘</span> errored ({state_counts["errored"]})</li>'
        f'<li><span class="cov-symbol cov-dark">▪</span> dark ({state_counts["dark"]})</li>'
        '</ul>'
    )
    body = (
        '<header class="coverage-hero">'
        f'<h1>Today’s coverage</h1>'
        f'<p class="coverage-subtitle">{len(cov)} stories × {len(buckets)} buckets · '
        f'<time datetime="{_e(date)}">{_e(_human_date(date))}</time></p>'
        '</header>'
        f'{legend_html}'
        f'<div class="coverage-matrix-wrap">{table_html}</div>'
        f'<p class="coverage-back"><a href="{SITE_BASE}/">← back to today</a></p>'
    )
    return _wrap_html_document(
        title=f"Coverage · {_human_date(date)}",
        og_title=f"Today’s coverage — {len(cov)} stories × {len(buckets)} buckets",
        og_description="Which buckets covered which stories, and which stayed silent.",
        body_class="coverage-page-body",
        main_class="coverage-page",
        main_content=body,
    )


# ---------------------------------------------------------------------------
# View 3: outlet fingerprint (108 auto-generated pages)
# ---------------------------------------------------------------------------

def render_outlet_page(bucket: str, outlet: str, tilt_data: dict) -> str:
    """Per-(bucket, outlet) tilt page. Handles BOTH pre-PR-7 (top-level
    positive_tilt/negative_tilt) and post-PR-7 (anchors.{wire,bucket_mean})
    shapes — falls back gracefully."""
    anchors = tilt_data.get("anchors") or {}
    if anchors:
        wire_pos = (anchors.get("wire") or {}).get("positive_tilt") or []
        wire_neg = (anchors.get("wire") or {}).get("negative_tilt") or []
        bm_pos = (anchors.get("bucket_mean") or {}).get("positive_tilt") or []
        bm_neg = (anchors.get("bucket_mean") or {}).get("negative_tilt") or []
    else:
        # Pre-PR-7 single-anchor shape
        wire_pos = tilt_data.get("positive_tilt") or []
        wire_neg = tilt_data.get("negative_tilt") or []
        bm_pos = []
        bm_neg = []

    def _tilt_table(rows: list[dict], anchor_label: str, max_n: int = 10) -> str:
        if not rows:
            return f'<p class="empty-state">No tilt data {anchor_label}.</p>'
        head = (
            '<thead><tr>'
            '<th>bigram</th>'
            '<th>count</th>'
            '<th>z</th>'
            '<th>log-odds</th>'
            '</tr></thead>'
        )
        body_rows = "".join(
            f'<tr>'
            f'<td>{_e(" ".join(r.get("bigram") or []))}</td>'
            f'<td class="num">{int(r.get("count_in_outlet") or 0)}</td>'
            f'<td class="num">{float(r.get("z_score") or 0):+.1f}</td>'
            f'<td class="num">{float(r.get("log_odds") or 0):+.2f}</td>'
            f'</tr>'
            for r in rows[:max_n]
        )
        return f'<table class="tilt-table">{head}<tbody>{body_rows}</tbody></table>'

    has_dual = bool(anchors)
    panels = (
        '<section class="tilt-anchor-panel">'
        '<h2>Over-represented vs wire baseline</h2>'
        f'{_tilt_table(wire_pos, "vs wire")}'
        '</section>'
    )
    if has_dual:
        panels += (
            '<section class="tilt-anchor-panel">'
            '<h2>Over-represented vs cross-bucket mean</h2>'
            f'{_tilt_table(bm_pos, "vs bucket mean")}'
            '</section>'
        )
    panels += (
        '<section class="tilt-anchor-panel">'
        '<h2>Suppressed vs wire baseline</h2>'
        f'{_tilt_table(wire_neg, "negative vs wire")}'
        '</section>'
    )

    n_articles = int(tilt_data.get("n_articles_in_window") or 0)
    window_days = int(tilt_data.get("window_days") or 0)
    wire_pin = tilt_data.get("wire_baseline_pin") or "?"

    disclaimer = (
        '<p class="tilt-disclaimer">'
        'log-odds vs wire baseline — descriptive, not normative. '
        'Wire ≠ truth-baseline; bucket-mean is one alternative anchor. '
        'Two-anchor presentation is the project’s honesty discipline; '
        f'see <a href="{SITE_BASE}/methodology/">methodology</a> for the rationale.'
        '</p>'
    )

    body = (
        '<header class="outlet-hero">'
        f'<p class="outlet-eyebrow">OUTLET FINGERPRINT</p>'
        f'<h1>{_flag(bucket)} {_e(outlet)}</h1>'
        f'<p class="outlet-subtitle">{_e(bucket)} · '
        f'{n_articles} articles in {window_days}-day window · '
        f'wire baseline pin v{_e(wire_pin)}</p>'
        '</header>'
        f'<div class="outlet-fingerprint">{panels}</div>'
        f'{disclaimer}'
        f'<p class="outlet-back"><a href="{SITE_BASE}/">← back to today</a></p>'
    )
    return _wrap_html_document(
        title=f"{outlet} · outlet fingerprint",
        og_title=f"{outlet} — vocabulary tilt vs wire baseline",
        og_description=f"What this outlet says distinctively. {n_articles} articles in window.",
        body_class="outlet-page-body",
        main_class="outlet-page",
        main_content=body,
    )


# ---------------------------------------------------------------------------
# View 4: methodology page
# ---------------------------------------------------------------------------

def render_methodology_page(
    meta_dict: dict,
    codebook: dict | None,
    prompt_md: str,
    card_picker: dict,
    today_picker: dict,
    todays_card: dict | None,
    drift_segment_md: str = "",
) -> str:
    """Replaces methodology-challenge.html. Surfaces the pin, codebook,
    analysis prompt, and the daily-card picker explanation."""
    pin_keys_with_doc = [
        ("meta_version", "Pin version. Bumped via baseline_pin.py."),
        ("pinned_at", "When this pin was created (UTC)."),
        ("pin_reason", "What changed in this bump."),
        ("schemas_hash", "Hash of every JSON schema in docs/api/schema/."),
        ("prompts_hash", "Hash of every prompt in .claude/prompts/."),
        ("canonical_stories_hash", "Hash of canonical_stories.json (story patterns)."),
        ("frames_codebook_hash", "Hash of frames_codebook.json (15 frames)."),
        ("bucket_quality_hash", "Hash of bucket_quality.json (per-bucket flags)."),
        ("bucket_weights_hash", "Hash of bucket_weights.json."),
        ("card_picker_hash", "Hash of card_picker.json (per-story archetype picker)."),
        ("today_picker_hash", "Hash of today_picker.json (daily hero picker)."),
        ("pin_self_hash", "Hash of the entire pin file (tamper evidence)."),
    ]
    pin_rows = ""
    for k, doc in pin_keys_with_doc:
        v = meta_dict.get(k)
        if v is None:
            continue
        if isinstance(v, str) and len(v) > 60 and v.startswith("sha256:"):
            v_display = f"<code>{_e(v[:20])}…{_e(v[-8:])}</code>"
        else:
            v_display = f"<code>{_e(v)}</code>"
        pin_rows += (
            f'<tr><th>{_e(k)}</th><td>{v_display}<br><small>{_e(doc)}</small></td></tr>'
        )
    pin_section = (
        '<section class="methodology-section">'
        '<h2>Today’s pin</h2>'
        '<p>Every artifact ships stamped with the pin version below. Bumping the pin requires '
        '<code>python baseline_pin.py --bump &lt;level&gt; --reason "…"</code>; CI rejects any '
        'edit that drifts from the declared hashes.</p>'
        f'<table class="methodology-pin"><tbody>{pin_rows}</tbody></table>'
        '</section>'
    )

    codebook_section = ""
    if codebook:
        frames_list = codebook.get("frames") or []
        if frames_list:
            rows = "".join(
                f'<tr><th><code>{_e(f.get("frame_id"))}</code></th>'
                f'<td><strong>{_e(f.get("label") or f.get("name") or "")}</strong>'
                f'<br>{_e(f.get("description") or "")}</td></tr>'
                for f in frames_list
            )
            codebook_section = (
                '<section class="methodology-section">'
                '<h2>The 15-frame codebook</h2>'
                '<p>Closed taxonomy from Boydstun &amp; Card (2014). Every <code>frame_id</code> '
                'emitted by the analyzer must be one of these IDs — that’s what makes '
                'longitudinal comparison defensible. Cross-cultural validity caveat: the '
                'codebook is calibrated on US-domestic coverage; it’s stretched on non-Anglo '
                'foreign-policy framings.</p>'
                f'<table class="methodology-codebook"><tbody>{rows}</tbody></table>'
                '</section>'
            )

    prompt_section = (
        '<section class="methodology-section">'
        '<h2>Today’s analysis prompt</h2>'
        '<p>This is the literal prompt the agent ran against today’s briefings. '
        'Its content is hashed into <code>prompts_hash</code> above.</p>'
        f'<pre class="methodology-prompt">{_e(prompt_md)}</pre>'
        '</section>'
    )

    picker_section_html = _picker_section(card_picker, today_picker, todays_card)

    drift_section = ""
    if drift_segment_md:
        drift_section = (
            '<section class="methodology-section">'
            '<h2>Pin drift</h2>'
            f'<pre class="methodology-drift">{_e(drift_segment_md)}</pre>'
            '</section>'
        )

    challenge_section = (
        '<section class="methodology-section">'
        '<h2>Challenge a framing</h2>'
        '<p>If you disagree with how a story was framed — not "you got a number wrong" '
        f'(that’s a <a href="{SITE_BASE}/corrections.html">correction</a>) but "your method picks '
        'a frame that erases X" — file a methodology challenge.</p>'
        '<p>Methodology challenges are GitHub issues with these elements:</p>'
        '<ol>'
        '<li>The specific claim you disagree with (story + bucket + frame).</li>'
        '<li>Which methodology element you think is wrong (codebook? prompt? feed set? '
        'pipeline step?).</li>'
        '<li>What the alternative call would be.</li>'
        '<li>Whether the disagreement is one-off (this story) or systemic (every story '
        'with property X).</li>'
        '</ol>'
        '<p>One-off challenges get logged in <code>methodology_challenges.json</code>. '
        'Systemic ones become candidates for the next major pin bump.</p>'
        '</section>'
    )

    body = (
        '<header class="methodology-hero">'
        '<h1>Methodology</h1>'
        '<p class="methodology-subtitle">How epistemic-lens analyses are produced · '
        f'meta v{_e(meta_dict.get("meta_version"))} · '
        f'pinned {_e(meta_dict.get("pinned_at"))}</p>'
        '</header>'
        f'{pin_section}{codebook_section}{prompt_section}{picker_section_html}{drift_section}{challenge_section}'
        f'<p class="methodology-back"><a href="{SITE_BASE}/">← back to today</a></p>'
    )
    return _wrap_html_document(
        title="Methodology · The Same Story",
        og_title="How epistemic-lens analyses are produced",
        og_description="The pin, the codebook, the prompt, and the picker — all on one page.",
        body_class="methodology-page-body",
        main_class="methodology-page",
        main_content=body,
    )


def _picker_section(card_picker: dict, today_picker: dict,
                     todays_card: dict | None) -> str:
    cascade = card_picker.get("cascade") or []
    cascade_rows = "".join(
        f'<li><strong>{_e(entry.get("kind"))}</strong>'
        f'<br><small>{_e(_summarise_precondition(entry.get("precondition") or {}))}</small></li>'
        for entry in cascade
    )
    weights = (today_picker.get("scoring") or {}).get("archetype_strength_weights") or {}
    weight_rows = "".join(
        f'<tr><td>{_e(k)}</td><td class="num">{float(v):.2f}</td></tr>'
        for k, v in weights.items()
    )
    today_pick = ""
    if todays_card:
        sb = todays_card.get("score_breakdown") or {}
        today_pick = (
            '<h3>Today’s pick</h3>'
            f'<p>Story: <strong>{_e(todays_card.get("story_title") or todays_card.get("story_key"))}</strong> · '
            f'archetype: <strong>{_e(todays_card.get("card_kind"))}</strong></p>'
            '<table class="methodology-scoredown"><tbody>'
            f'<tr><th>magnitude</th><td>{float(sb.get("magnitude") or 0):.3f}</td></tr>'
            f'<tr><th>archetype strength</th><td>{float(sb.get("archetype_strength") or 0):.3f}</td></tr>'
            f'<tr><th>diversity bonus</th><td>{float(sb.get("diversity_bonus") or 0):.3f}</td></tr>'
            f'<tr><th>final score</th><td>{float(sb.get("final_score") or 0):.3f}</td></tr>'
            '</tbody></table>'
        )
    return (
        '<section class="methodology-section">'
        '<h2>How today’s hero was picked</h2>'
        '<p>Per-story archetype assignment runs a cascade — first matching precondition wins.</p>'
        f'<ol class="methodology-cascade">{cascade_rows}</ol>'
        '<p>Daily hero scoring across stories: '
        '<code>(magnitude + archetype_strength) × diversity_bonus</code>. Weights per archetype:</p>'
        f'<table class="methodology-weights"><tbody>{weight_rows}</tbody></table>'
        f'{today_pick}'
        '</section>'
    )


def _summarise_precondition(precond: dict) -> str:
    t = precond.get("type")
    if t == "fallback":
        return "fallback (no other archetype matched)"
    if t == "field_present":
        path = precond.get("path", "?")
        sub = precond.get("and")
        and_clause = f" and {_summarise_precondition(sub)}" if sub else ""
        return f"{path} is non-null{and_clause}"
    if t == "min_length":
        return f"{precond.get('path', '?')} has at least {precond.get('min', 0)} characters"
    if t == "max_abs_delta_share":
        return (f"trajectory: max |Δshare| in last {precond.get('lookback_days', 7)} days "
                f"≥ {float(precond.get('min', 0)):.2f}")
    if t == "count_in_state":
        extra = precond.get("additional_bucket_filter") or {}
        flt = f" with {extra.get('field')} < {extra.get('value')}" if extra else ""
        return (f"coverage: ≥ {precond.get('min_count', 0)} buckets in state "
                f"'{precond.get('state')}'{flt}")
    if t == "max_z_score":
        return f"tilt: any outlet anchor max z-score ≥ {float(precond.get('min', 0)):.1f}"
    if t == "sources_diversity":
        return (f"sources: ≥ {precond.get('min_total', 0)} speakers, "
                f"≥ {precond.get('min_distinct_buckets', 0)} buckets, "
                f"≥ {precond.get('min_distinct_speaker_affiliation_buckets', 0)} affiliation types")
    if t == "max_llr":
        return f"vocab: top distinctive_term llr ≥ {float(precond.get('min', 0)):.0f}"
    return str(precond)


# ---------------------------------------------------------------------------
# View 5: archive browser
# ---------------------------------------------------------------------------

def render_archive_page(date_indexes: list[tuple[str, dict]]) -> str:
    """Chronological table of every published date.

    `date_indexes` is a list of (date_str, api/<date>/index.json dict) tuples,
    most-recent-first.
    """
    # Group by month for visual breaks.
    rows: list[str] = []
    last_month = ""
    total_stories = 0
    for date_str, idx in date_indexes:
        try:
            d = _date.fromisoformat(date_str)
        except ValueError:
            continue
        month_label = d.strftime("%B %Y")
        if month_label != last_month:
            rows.append(f'<tr class="archive-month-row"><th colspan="4">{_e(month_label)}</th></tr>')
            last_month = month_label
        stories = idx.get("stories") or []
        total_stories += len(stories)
        todays_card = idx.get("todays_card") or {}
        hero_kind = _e(todays_card.get("card_kind", "—"))
        hero_story = _e(todays_card.get("story_title") or todays_card.get("story_key", "—"))
        # Stories list compact: first 3 + count
        stories_compact = ", ".join(
            _e((s.get("title") or s.get("key", ""))[:30])
            for s in stories[:3]
        )
        if len(stories) > 3:
            stories_compact += f" + {len(stories) - 3} more"
        rows.append(
            '<tr class="archive-day-row">'
            f'<td class="archive-date"><a href="{SITE_BASE}/{_e(date_str)}/">{_e(date_str)}</a></td>'
            f'<td class="archive-hero"><span class="archive-hero-kind">{hero_kind}</span> {hero_story}</td>'
            f'<td class="archive-stories">{stories_compact}</td>'
            f'<td class="archive-count num">{len(stories)}</td>'
            '</tr>'
        )

    body = (
        '<header class="archive-hero">'
        '<h1>Archive</h1>'
        f'<p class="archive-subtitle">{len(date_indexes)} days · {total_stories} stories total</p>'
        '</header>'
        '<table class="archive-table">'
        '<thead><tr>'
        '<th>date</th>'
        '<th>today’s pick (archetype + story)</th>'
        '<th>other stories</th>'
        '<th class="num">n</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        f'<p class="archive-back"><a href="{SITE_BASE}/">← back to today</a></p>'
    )
    return _wrap_html_document(
        title="Archive · The Same Story",
        og_title=f"Archive — {len(date_indexes)} days",
        og_description="Every day epistemic-lens has published.",
        body_class="archive-page-body",
        main_class="archive-page",
        main_content=body,
    )


# ---------------------------------------------------------------------------
# Common HTML shell
# ---------------------------------------------------------------------------

def _wrap_html_document(*, title: str, og_title: str, og_description: str,
                         body_class: str, main_class: str, main_content: str) -> str:
    """Common <html> shell — keeps the home page's head/footer pattern."""
    footer = (
        '<footer class="site-footer">'
        f'<a href="{SITE_BASE}/methodology/">methodology</a>'
        f'<a href="{SITE_BASE}/corrections.html">corrections</a>'
        f'<a href="{SITE_BASE}/archive/">archive</a>'
        f'<span>meta · v{_e(meta.VERSION)}</span>'
        '</footer>'
    )
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <meta property="og:title" content="{_e(og_title)}">
  <meta property="og:description" content="{_e(og_description)}">
  <link rel="stylesheet" href="{SITE_BASE}/styles.css">
</head>
<body class="{_e(body_class)}">
<main class="{_e(main_class)}">{main_content}</main>
{footer}
<script src="{SITE_BASE}/app.js" defer></script>
</body>
</html>
'''


# ===========================================================================
# Plan 4: 4-card home page with cubes
# ===========================================================================

def _cube_shell(kind: str, label: str, thing_html: str, caption: str,
                 open_html: str, group: str) -> str:
    """Wrap a cube as a <details name=...> with the three-layer typographic
    structure inside <summary> (closed state) + the open-state body."""
    return (
        f'<details class="cube cube--{_e(kind)}" name="{_e(group)}">'
        f'<summary>'
        f'<p class="cube-label">{_e(label)}</p>'
        f'<span class="cube-rule"></span>'
        f'<div class="cube-thing">{thing_html}</div>'
        f'<span class="cube-rule"></span>'
        f'<p class="cube-caption">{_e(caption)}</p>'
        f'</summary>'
        f'<div class="cube-open">{open_html}</div>'
        f'</details>'
    )


def _short_quote_word(quote: str) -> str:
    """Pluck the SHORTEST salient single-quoted word/phrase from an
    evidence quote. Falls back to the longest content word."""
    if not quote:
        return ""
    # Try ‘…’ or '…' or "…" single-quote contents inside the quote
    m = re.search(r"[‘']([^’'\"]{3,40})[’']", quote)
    if m:
        return m.group(1).strip()
    # Then "…" double-quote contents
    m = re.search(r'["“]([^"”]{3,40})["”]', quote)
    if m:
        return m.group(1).strip()
    # Fallback: take the longest content word ≥6 chars
    words = [w.strip('.,;:!?"\'()[]') for w in quote.split() if len(w) >= 6]
    if not words:
        return quote[:24]
    return max(words, key=len)


def _cube_tension(today_card: dict, signals: dict, group: str) -> str:
    """TENSION — paradox quotes when present; most-divergent pair fallback."""
    analysis = signals.get("analysis") or {}
    p = analysis.get("paradox")
    if p and (p.get("joint_conclusion") or "") and len(p["joint_conclusion"]) >= 60:
        a_word = _short_quote_word(p["a"].get("quote", ""))
        b_word = _short_quote_word(p["b"].get("quote", ""))
        joint = (p.get("joint_conclusion") or "").strip()
        # Take first sentence of joint for the teaser
        joint_teaser = joint.split(". ")[0]
        if len(joint_teaser) > 100:
            joint_teaser = joint_teaser[:97] + "…"
        thing = (
            f'<span class="cube-quote">“{_e(a_word)}”</span>'
            f' <span class="symbol">↔</span> '
            f'<span class="cube-quote">“{_e(b_word)}”</span>'
            f'<p class="cube-joint">{_e(joint_teaser)}</p>'
        )
        caption = f"{_e(p['a'].get('bucket', '?'))} vs {_e(p['b'].get('bucket', '?'))} · paradox"
        # Open state: reuse _render_paradox body
        from publication.card_renderers import _render_paradox
        tc = dict(today_card, card_kind="paradox")
        open_html = _render_paradox(tc, signals)
    else:
        # Fall back to most-divergent pair from metrics
        metrics = _signals_metrics(signals)
        ps = sorted((metrics.get("pairwise_similarity") or []),
                     key=lambda r: float(r.get("score") or 0))
        if ps:
            r = ps[0]
            thing = (
                f'<span class="cube-bucket">{_e(r.get("a"))}</span>'
                f' <span class="symbol">⟷</span> '
                f'<span class="cube-bucket">{_e(r.get("b"))}</span>'
                f'<p class="cube-bignum">{float(r.get("score") or 0):.2f}</p>'
            )
            caption = "most-divergent pair · LaBSE cosine"
            open_html = _render_pair_list(metrics, n=5, reverse=False)
        else:
            thing = '<p class="cube-empty">no tension signal today</p>'
            caption = "framing variance accruing"
            open_html = '<p>No paradox; metrics data not yet computed.</p>'
    return _cube_shell("tension", "TENSION", thing, caption, open_html, group)


def _cube_words(today_card: dict, signals: dict, group: str) -> str:
    """WORDS — top 3 distinctive bigrams (PMI) or terms (LLR) with ≠."""
    pmi = (signals.get("within_lang_pmi") or {}).get("by_bucket") or {}
    rows: list[tuple[str, str, float]] = []  # (bucket, phrase, score)
    for bucket, data in pmi.items():
        assocs = data.get("associations") or []
        if assocs:
            top = assocs[0]
            bg = top.get("bigram") or []
            phrase = " ".join(bg) if isinstance(bg, list) and len(bg) == 2 else ""
            if phrase:
                rows.append((bucket, phrase, float(top.get("z_score", 0))))
    # If too few bigrams, fall back to LLR single terms.
    if len(rows) < 3:
        llr = (signals.get("within_lang_llr") or {}).get("by_bucket") or {}
        for bucket, data in llr.items():
            terms = data.get("distinctive_terms") or []
            if terms:
                top = terms[0]
                rows.append((bucket, top.get("term", ""), float(top.get("llr", 0))))
    rows.sort(key=lambda r: -r[2])
    rows = rows[:3]
    if not rows:
        thing = '<p class="cube-empty">vocabulary signal accruing</p>'
        caption = "within-language LLR/PMI"
        open_html = '<p>No distinctive terms yet — corpus too sparse.</p>'
    else:
        # Two patterns: 1-line if all words are short, else stacked
        all_short = all(len(r[1]) <= 18 for r in rows)
        if all_short and len(rows) == 3:
            thing = (
                f'<span class="cube-word">{_e(rows[0][1])}</span>'
                f' <span class="symbol">≠</span> '
                f'<span class="cube-word">{_e(rows[1][1])}</span>'
                f' <span class="symbol">≠</span> '
                f'<span class="cube-word">{_e(rows[2][1])}</span>'
            )
        else:
            parts = (f'<span class="cube-word">{_e(w)}</span>' for _, w, _ in rows)
            thing = ' <span class="symbol">≠</span><br>'.join(parts)
        scores = " / ".join(f"{int(round(r[2]))}" for r in rows)
        caption = f"{len(rows)} buckets · z/LLR {scores}"
        # Open state: full _render_word for top 6 buckets
        from publication.card_renderers import _render_word
        tc = dict(today_card, card_kind="word")
        open_html = _render_word(tc, signals)
    return _cube_shell("words", "WORDS", thing, caption, open_html, group)


def _cube_silence(today_card: dict, signals: dict, group: str) -> str:
    """SILENCE — bucket constellation ●○ + what-they-covered-instead caption."""
    story_key = signals.get("story_key")
    coverage = signals.get("coverage") or {}
    # Build state-per-bucket map for THIS story.
    cov_data = coverage.get("coverage") or {}
    story_cov = cov_data.get(story_key) or []
    # Aggregate per-bucket: covered if any feed had n_matching>0; silent if all zero
    per_bucket: dict[str, str] = {}
    for r in story_cov:
        b = r.get("bucket")
        if not b:
            continue
        n = int(r.get("n_matching") or 0)
        prev = per_bucket.get(b)
        if n > 0:
            per_bucket[b] = "covered"
        elif prev != "covered":
            per_bucket[b] = "silent"
    buckets_sorted = sorted(per_bucket.keys())
    constellation = "".join("●" if per_bucket[b] == "covered" else "○" for b in buckets_sorted)
    n_total = len(per_bucket)
    n_silent = sum(1 for v in per_bucket.values() if v == "silent")
    # Editorial annotation from analysis.silences (when present)
    analysis = signals.get("analysis") or {}
    sil_list = analysis.get("silences") or []
    annotation = ""
    if sil_list:
        top = sil_list[0]
        sb = top.get("bucket", "?")
        instead = (top.get("what_they_covered_instead") or "").strip()
        if instead:
            # First clause only, ≤80 chars
            first = instead.split(";")[0].split(". ")[0]
            if len(first) > 80:
                first = first[:77] + "…"
            annotation = f"{sb} ran {first}"
    if not annotation and n_silent > 0:
        annotation = f"{n_silent} silent bucket{'s' if n_silent != 1 else ''}"
    if n_silent == 0:
        annotation = "convergent coverage"

    thing = f'<p class="constellation">{constellation or "—"}</p>'
    caption = (
        f"{n_total - n_silent} of {n_total} carried · {annotation}"
        if n_silent > 0
        else f"{n_total} of {n_total} carried · {annotation}"
    )
    from publication.card_renderers import _render_silence
    tc = dict(today_card, card_kind="silence")
    open_html = _render_silence(tc, signals)
    return _cube_shell("silence", "SILENCE", thing, caption, open_html, group)


def _cube_voices(today_card: dict, signals: dict, group: str) -> str:
    """VOICES — analyst editorial: vocab.what_it_reveals or single_outlet_finding."""
    analysis = signals.get("analysis") or {}
    # Primary: exclusive_vocab_highlights[0].what_it_reveals
    ev = analysis.get("exclusive_vocab_highlights") or []
    if ev and (ev[0].get("what_it_reveals") or ""):
        reveal = (ev[0].get("what_it_reveals") or "").strip()
        # Cap at ~140 chars for cube; clamp at sentence boundary
        if len(reveal) > 140:
            cut = reveal[:140].rsplit(".", 1)[0]
            reveal = (cut + ".") if cut else reveal[:137] + "…"
        bucket = ev[0].get("bucket", "?")
        n_terms = len(ev[0].get("terms") or [])
        thing = f'<blockquote class="cube-blockquote">{_e(reveal)}</blockquote>'
        caption = f"{bucket} · {n_terms} distinctive terms"
        source = "vocab"
    else:
        # Fallback: single_outlet_findings[0]
        sof = analysis.get("single_outlet_findings") or []
        if sof and (sof[0].get("finding") or ""):
            finding = (sof[0].get("finding") or "").strip()
            if len(finding) > 140:
                cut = finding[:140].rsplit(".", 1)[0]
                finding = (cut + ".") if cut else finding[:137] + "…"
            outlet = sof[0].get("outlet", "?")
            bucket = sof[0].get("bucket", "?")
            thing = f'<blockquote class="cube-blockquote">{_e(finding)}</blockquote>'
            caption = f"{outlet} · {bucket} · analyst pick"
            source = "outlet finding"
        else:
            # Final fallback: bottom_line first sentence
            bl = (analysis.get("bottom_line") or "").strip()
            if bl:
                first = bl.split(". ")[0]
                if len(first) > 140:
                    first = first[:137] + "…"
                thing = f'<blockquote class="cube-blockquote">{_e(first)}.</blockquote>'
                n_buckets = analysis.get("n_buckets", 0)
                caption = f"bottom line · {n_buckets}-bucket synthesis"
                source = "bottom line"
            else:
                thing = '<p class="cube-empty">analyst commentary accruing</p>'
                caption = "no editorial findings"
                source = "—"

    # Open state: full vocab + findings list
    open_html = _render_voices_open(analysis)
    return _cube_shell("voices", "VOICES", thing, caption, open_html, group)


def _cube_frames(today_card: dict, signals: dict, group: str) -> str:
    """FRAMES — top 3 frame_id : sub_frame by bucket count."""
    analysis = signals.get("analysis") or {}
    frames = analysis.get("frames") or []
    if not frames:
        thing = '<p class="cube-empty">frame analysis accruing</p>'
        caption = "no frames detected"
        open_html = '<p>No frames present.</p>'
    else:
        # Sort by bucket count descending
        ranked = sorted(frames, key=lambda f: -len(f.get("buckets") or []))[:3]
        rows: list[str] = []
        for f in ranked:
            fid = f.get("frame_id", "?")
            sub = f.get("sub_frame", "")
            # Truncate frame_id display for tight layout
            fid_short = fid[:13]
            rows.append(
                f'<div class="frames-row">'
                f'<span class="frame-id">{_e(fid_short)}</span>'
                f'<span class="frame-sub">{_e(sub or "—")}</span>'
                f'</div>'
            )
        thing = "".join(rows)
        total = len(frames)
        n_buckets_carrying = sum(len(f.get("buckets") or []) for f in ranked)
        caption = f"{len(ranked)} of {total} frames · {n_buckets_carrying} buckets"
        open_html = render_frames_matrix(analysis)
    return _cube_shell("frames", "FRAMES", thing, caption, open_html, group)


def _cube_contrast(today_card: dict, signals: dict, group: str) -> str:
    """CONTRAST — most-similar pair (≈) AND most-divergent pair (⟷) bookended."""
    metrics = _signals_metrics(signals)
    ps_sorted = sorted((metrics.get("pairwise_similarity") or []),
                        key=lambda r: float(r.get("score") or 0))
    if len(ps_sorted) < 2:
        thing = '<p class="cube-empty">pairwise data accruing</p>'
        caption = "metrics not yet computed"
        open_html = '<p>No pairwise similarity data.</p>'
    else:
        low, high = ps_sorted[0], ps_sorted[-1]
        thing = (
            f'<div class="contrast-row">'
            f'<span class="cube-bucket">{_e(high.get("a"))}</span>'
            f' <span class="symbol">≈</span> '
            f'<span class="cube-bucket">{_e(high.get("b"))}</span>'
            f'<span class="contrast-score">{float(high.get("score") or 0):.2f}</span>'
            f'</div>'
            f'<div class="contrast-row">'
            f'<span class="cube-bucket">{_e(low.get("a"))}</span>'
            f' <span class="symbol">⟷</span> '
            f'<span class="cube-bucket">{_e(low.get("b"))}</span>'
            f'<span class="contrast-score">{float(low.get("score") or 0):.2f}</span>'
            f'</div>'
        )
        caption = "LaBSE bucket-mean cosine"
        open_html = (
            '<h3>Most similar (top 5)</h3>'
            + _render_pair_list(metrics, n=5, reverse=True)
            + '<h3>Most divergent (bottom 5)</h3>'
            + _render_pair_list(metrics, n=5, reverse=False)
        )
    return _cube_shell("contrast", "CONTRAST", thing, caption, open_html, group)


# ---------------------------------------------------------------------------
# Helpers for cube content
# ---------------------------------------------------------------------------

def _signals_metrics(signals: dict) -> dict:
    """Pull metrics dict from signals; load from disk on demand."""
    m = signals.get("metrics")
    if isinstance(m, dict):
        return m
    date = signals.get("date") or ""
    story_key = signals.get("story_key") or ""
    p = meta.REPO_ROOT / "briefings" / f"{date}_{story_key}_metrics.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _render_pair_list(metrics: dict, *, n: int, reverse: bool) -> str:
    """List of N pairwise similarity rows. reverse=True → most similar first."""
    ps = sorted((metrics.get("pairwise_similarity") or []),
                 key=lambda r: float(r.get("score") or 0),
                 reverse=reverse)[:n]
    rows = "".join(
        f'<li>'
        f'<span class="pair-a">{_e(r.get("a"))}</span>'
        f' <span class="pair-sep">{"≈" if reverse else "⟷"}</span> '
        f'<span class="pair-b">{_e(r.get("b"))}</span>'
        f'<span class="pair-score">{float(r.get("score") or 0):.3f}</span>'
        f'</li>'
        for r in ps
    )
    return f'<ol class="pair-list">{rows}</ol>'


def _render_voices_open(analysis: dict) -> str:
    """Open-state of VOICES cube: every vocab.what_it_reveals + every single_outlet_finding."""
    parts: list[str] = []
    ev = analysis.get("exclusive_vocab_highlights") or []
    if ev:
        parts.append('<h3>Distinctive vocabulary</h3>')
        for h in ev:
            terms = ", ".join(_e(t) for t in (h.get("terms") or []))
            parts.append(
                f'<div class="voice-block">'
                f'<p class="voice-block-head">{_e(h.get("bucket"))} · <em>{terms}</em></p>'
                f'<p class="voice-block-body">{_e(h.get("what_it_reveals") or "")}</p>'
                f'</div>'
            )
    sof = analysis.get("single_outlet_findings") or []
    if sof:
        parts.append('<h3>Single-outlet findings</h3>')
        for s in sof:
            parts.append(
                f'<div class="voice-block">'
                f'<p class="voice-block-head">{_e(s.get("outlet"))} · {_e(s.get("bucket"))}</p>'
                f'<p class="voice-block-body">{_e(s.get("finding") or "")}</p>'
                f'</div>'
            )
    if not parts:
        return '<p>No editorial commentary on this story today.</p>'
    return "".join(parts)


# ---------------------------------------------------------------------------
# Headlines strip
# ---------------------------------------------------------------------------

def _render_headlines_strip(briefing: dict, analysis: dict) -> str:
    """Pick 4 contrasting article titles from the corpus — one per frame
    (top 4 frames by bucket count). Skip duplicate buckets."""
    corpus = briefing.get("corpus") or []
    if not corpus or not analysis.get("frames"):
        return ""
    frames = sorted(analysis["frames"], key=lambda f: -len(f.get("buckets") or []))
    seen_buckets: set[str] = set()
    picks: list[dict] = []
    for f in frames:
        for ev in f.get("evidence") or []:
            idx = ev.get("signal_text_idx")
            if not isinstance(idx, int) or idx < 0 or idx >= len(corpus):
                continue
            item = corpus[idx]
            bucket = item.get("bucket")
            if bucket in seen_buckets:
                continue
            seen_buckets.add(bucket)
            picks.append(item)
            break  # only one per frame
        if len(picks) >= 4:
            break
    if not picks:
        return ""
    items = "".join(
        f'<li>'
        f'<span class="flag">{_flag(p.get("bucket"))}</span>'
        f'<a class="title" href="{_e(p.get("link") or "#")}" rel="noopener">'
        f'{_e((p.get("title") or "")[:120])}'
        f'</a>'
        f'<span class="feed">{_e(p.get("feed") or "")}</span>'
        f'</li>'
        for p in picks
    )
    return (
        '<section class="card-headlines">'
        '<p class="card-headlines-label">HEADLINES</p>'
        f'<ol>{items}</ol>'
        '</section>'
    )


# ---------------------------------------------------------------------------
# Story card composer
# ---------------------------------------------------------------------------

def _render_story_card(date: str, story_entry: dict, signals: dict,
                        briefing: dict) -> str:
    """One story card: header + headlines strip + 6 cubes + footer."""
    analysis = signals.get("analysis") or {}
    story_key = story_entry["key"]
    story_title = story_entry.get("title") or story_key
    event_summary = (
        story_entry.get("event_summary")
        or analysis.get("event_summary")
        or analysis.get("tldr")
        or ""
    )
    n_buckets = story_entry.get("n_buckets") or analysis.get("n_buckets") or 0
    n_articles = story_entry.get("n_articles") or analysis.get("n_articles") or 0
    n_frames = len(analysis.get("frames") or [])
    sources = (signals.get("sources") or {}).get("sources") or []
    n_sources = len(sources)

    header = (
        '<header class="story-card-header">'
        f'<p class="card-eyebrow">'
        f'<span>{_e(story_key.upper().replace("_", " · "))}</span>'
        f'<time datetime="{_e(date)}">{_e(_human_date(date))}</time>'
        f'</p>'
        f'<h2 class="card-headline">{_e(story_title)}</h2>'
        f'<p class="card-kicker">{_e(event_summary)}</p>'
        f'<p class="card-meta">'
        f'{n_buckets} buckets · {n_articles} articles · '
        f'{n_frames} frames · {n_sources} sources'
        f'</p>'
        '</header>'
    )

    headlines = _render_headlines_strip(briefing, analysis)

    # today_card carries common fields the inner _render_<kind> functions
    # need for their internal logic (story_key for non_coverage lookup etc).
    today_card = {
        "card_kind": "",
        "date": date,
        "story_key": story_key,
        "story_title": story_title,
        "headline": story_title,
        "kicker": event_summary,
        "finding_synthesis": "",
        "meta_version": meta.VERSION,
        "see_how_path": f"{SITE_BASE}/{date}/{story_key}/",
    }
    group = f"cubes-{story_key}"

    cubes = (
        '<section class="card-cubes">'
        + _cube_tension(today_card, signals, group)
        + _cube_words(today_card, signals, group)
        + _cube_silence(today_card, signals, group)
        + _cube_voices(today_card, signals, group)
        + _cube_frames(today_card, signals, group)
        + _cube_contrast(today_card, signals, group)
        + '</section>'
    )

    footer = (
        '<footer class="card-footer-actions">'
        f'<a href="{SITE_BASE}/{date}/{story_key}/">permalink ↗</a>'
        f'<a href="{SITE_BASE}/{date}/{story_key}/#story-{story_key}-essay">read essay ↓</a>'
        '</footer>'
    )

    return (
        f'<article class="story-card" id="story-{_e(story_key)}">'
        f'{header}{headlines}{cubes}{footer}'
        '</article>'
    )


# ---------------------------------------------------------------------------
# Today card (4th card) — meta cubes
# ---------------------------------------------------------------------------

def _render_today_card(date: str, all_story_entries: list[dict],
                        picked_keys: list[str]) -> str:
    """The 4th card. Same shape as story cards but cubes carry meta-signals
    drawn from coverage/, trajectory/, briefings/, and the daily index."""
    group = "cubes-today"
    n_stories = len(all_story_entries)
    # Active buckets today: union from coverage/<date>.json
    coverage_path = meta.REPO_ROOT / "coverage" / f"{date}.json"
    n_buckets_active = 0
    n_buckets_total = 0
    active_constellation = ""
    if coverage_path.exists():
        try:
            cov = json.loads(coverage_path.read_text(encoding="utf-8"))
            feeds = cov.get("feeds") or []
            all_buckets = sorted({f.get("bucket") for f in feeds if f.get("bucket")})
            n_buckets_total = len(all_buckets)
            # Bucket is "active" if ANY story had ≥1 article from it
            active: set[str] = set()
            for sk, recs in (cov.get("coverage") or {}).items():
                for r in recs:
                    if int(r.get("n_matching") or 0) > 0:
                        b = r.get("bucket")
                        if b:
                            active.add(b)
            n_buckets_active = len(active)
            active_constellation = "".join(
                "●" if b in active else "○" for b in all_buckets
            )
        except (OSError, json.JSONDecodeError):
            pass

    # Articles total: sum n_articles across stories
    n_articles = sum(s.get("n_articles") or 0 for s in all_story_entries)

    # Languages distribution: walk today's briefings
    from collections import Counter
    lang_counts: Counter[str] = Counter()
    for s in all_story_entries:
        bpath = meta.REPO_ROOT / "briefings" / f"{date}_{s['key']}.json"
        if bpath.exists():
            try:
                b = json.loads(bpath.read_text(encoding="utf-8"))
                for c in b.get("corpus") or []:
                    lg = (c.get("lang") or "??").lower()
                    lang_counts[lg] += 1
            except (OSError, json.JSONDecodeError):
                pass

    # Biggest framing-share move today: walk trajectories for picked stories
    biggest_move = (None, 0.0, None, None)  # (story, abs, signed, frame)
    for s in all_story_entries:
        tpath = meta.REPO_ROOT / "trajectory" / f"{s['key']}.json"
        if not tpath.exists():
            continue
        try:
            t = json.loads(tpath.read_text(encoding="utf-8"))
            for fid, entries in (t.get("frame_trajectories") or {}).items():
                for e in entries:
                    d = e.get("delta_share")
                    if d is None:
                        continue
                    if abs(d) > biggest_move[1]:
                        biggest_move = (s["key"], abs(d), d, fid)
        except (OSError, json.JSONDecodeError):
            pass

    # ---- TODAY cube ----
    today_thing = (
        f'<p class="cube-bignum-stacked">{n_stories} stories</p>'
        f'<p class="cube-bignum-sub">{n_buckets_active} buckets active · {n_articles} articles</p>'
    )
    today_cube = _cube_shell(
        "today", "TODAY", today_thing,
        f"{_human_date(date)} · pin v{meta.VERSION}",
        f'<p>{n_stories} stories analyzed; {n_buckets_active} of {n_buckets_total} buckets carried at least one. {n_articles} articles ingested.</p>',
        group,
    )

    # ---- SPREAD cube ----
    spread_thing = f'<p class="constellation small">{active_constellation or "—"}</p>'
    spread_cube = _cube_shell(
        "spread", "SPREAD", spread_thing,
        f"{n_buckets_active} of {n_buckets_total} buckets covered ≥1 story",
        f'<p>Bucket activity across all {n_stories} stories today. Hollow circles = bucket dark or no feeds matched on any story.</p>',
        group,
    )

    # ---- LEADS cube ----
    leads_rows: list[str] = []
    for s in all_story_entries[:4]:
        kind = s.get("card_kind", "—").upper()
        synth = (s.get("finding_synthesis") or s.get("event_summary") or "")[:32]
        marker = "★ " if s["key"] in picked_keys else "  "
        leads_rows.append(
            f'<div class="leads-row">'
            f'<span class="leads-marker">{marker}</span>'
            f'<span class="leads-kind">{_e(kind):<8}</span>'
            f'<span class="leads-key">{_e(s["key"])}</span>'
            f'</div>'
        )
    leads_thing = "".join(leads_rows) or '<p class="cube-empty">no leads</p>'
    leads_cube = _cube_shell(
        "leads", "LEADS", leads_thing,
        f"{len(picked_keys)} picked · {n_stories - len(picked_keys)} other stories",
        '<p>★ marks stories that earned their own card on this home page; remaining stories live on the per-date manifest.</p>',
        group,
    )

    # ---- LANGUAGES cube ----
    if lang_counts:
        top_langs = lang_counts.most_common(5)
        total_lang = sum(lang_counts.values())
        rows: list[str] = []
        for lg, n in top_langs:
            pct = (n * 100 // total_lang) if total_lang else 0
            bar = "█" * max(1, pct // 8) + "░" * (12 - max(1, pct // 8))
            rows.append(
                f'<div class="lang-row">'
                f'<span class="lang-code">{_e(lg.upper()):<3}</span>'
                f'<span class="lang-bar">{bar}</span>'
                f'<span class="lang-count">{n}</span>'
                f'</div>'
            )
        lang_thing = "".join(rows)
        caption = f"{len(lang_counts)} languages · {total_lang} articles"
    else:
        lang_thing = '<p class="cube-empty">language data accruing</p>'
        caption = "no briefings loaded"
    lang_cube = _cube_shell(
        "languages", "LANGUAGES", lang_thing, caption,
        f'<p>Distribution of article-source languages across today\'s briefings.</p>',
        group,
    )

    # ---- MOVES cube ----
    if biggest_move[0]:
        story, _, signed, fid = biggest_move
        direction = "↑" if signed > 0 else "↓"
        moves_thing = (
            f'<p class="cube-bignum">{direction} {abs(signed) * 100:.0f}pp</p>'
            f'<p class="cube-bignum-sub">{_e(fid)} frame</p>'
        )
        caption_moves = f"{_e(story)} · biggest framing shift"
    else:
        moves_thing = '<p class="cube-empty">trajectory data accruing</p>'
        caption_moves = "no multi-day data yet"
    moves_cube = _cube_shell(
        "moves", "MOVES", moves_thing, caption_moves,
        '<p>The largest day-over-day frame-share movement across today\'s stories. Driver URLs available on the per-story page.</p>',
        group,
    )

    # ---- LINKS cube ----
    links_thing = (
        '<ul class="links-list">'
        f'<li><a href="{SITE_BASE}/{date}/coverage.html">coverage matrix →</a></li>'
        f'<li><a href="{SITE_BASE}/archive/">archive →</a></li>'
        f'<li><a href="{SITE_BASE}/methodology/">methodology →</a></li>'
        '</ul>'
    )
    links_cube = _cube_shell(
        "links", "LINKS", links_thing,
        "deeper · per-story · per-outlet",
        '<p>Navigate to the depth views: today\'s coverage matrix, the publication archive, or the methodology page (pin + codebook + prompt).</p>',
        group,
    )

    header = (
        '<header class="story-card-header today-card-header">'
        '<p class="card-eyebrow">'
        '<span>TODAY · STATE OF THE LENS</span>'
        f'<time datetime="{_e(date)}">{_e(_human_date(date))}</time>'
        '</p>'
        '<h2 class="card-headline">The same story, today</h2>'
        f'<p class="card-kicker">{n_stories} stories · {n_buckets_active} buckets active · pin v{_e(meta.VERSION)}</p>'
        '</header>'
    )

    cubes = (
        '<section class="card-cubes">'
        + today_cube + spread_cube + leads_cube
        + lang_cube + moves_cube + links_cube
        + '</section>'
    )

    return f'<article class="today-card">{header}{cubes}</article>'


# ---------------------------------------------------------------------------
# Top-level home page composer
# ---------------------------------------------------------------------------

def render_home_page(date: str, picked_stories: list[dict],
                      all_story_entries: list[dict],
                      signals_by_key: dict, briefings_by_key: dict) -> str:
    """Compose the 4-card home page.

    Args:
        date: the date being rendered (YYYY-MM-DD).
        picked_stories: top-N story entries (typically 3) that get their own card.
        all_story_entries: every story entry on api/<date>/index.json (for the
            "Today" card's LEADS cube).
        signals_by_key: {story_key: collect_story_signals(date, key, briefing)}
        briefings_by_key: {story_key: briefing dict from briefings/<date>_<key>.json}
    """
    story_cards = "".join(
        _render_story_card(date, entry, signals_by_key.get(entry["key"], {}),
                            briefings_by_key.get(entry["key"], {}))
        for entry in picked_stories
    )
    picked_keys = [s["key"] for s in picked_stories]
    today_card = _render_today_card(date, all_story_entries, picked_keys)
    grid = (
        '<div class="home-card-grid">'
        + story_cards + today_card
        + '</div>'
    )
    # Hero title above grid
    hero = (
        '<header class="home-hero">'
        '<p class="home-eyebrow">THE SAME STORY</p>'
        '<h1 class="home-title">How the world told the same news today.</h1>'
        f'<p class="home-meta">{_e(_human_date(date))} · pin v{_e(meta.VERSION)}</p>'
        '</header>'
    )
    body = hero + grid
    # OG description from top picked story's event_summary
    og_desc = ""
    if picked_stories:
        a = signals_by_key.get(picked_stories[0]["key"], {}).get("analysis") or {}
        og_desc = (a.get("event_summary") or a.get("tldr") or "")[:200]

    return _wrap_html_document(
        title=f"The Same Story · {_human_date(date)}",
        og_title=f"How the world told the same news today · {_human_date(date)}",
        og_description=og_desc,
        body_class="home-page-body",
        main_class="home-page",
        main_content=body,
    )

