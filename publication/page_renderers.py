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
        '<p class="story-page-back"><a href="/">← back to today</a></p>'
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
            f'<tr><th class="cov-story-header"><a href="/{_e(date)}/{_e(sk)}/">{_e(story_title.get(sk, sk))}</a></th>'
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
        '<p class="coverage-back"><a href="/">← back to today</a></p>'
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
        'see <a href="/methodology/">methodology</a> for the rationale.'
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
        '<p class="outlet-back"><a href="/">← back to today</a></p>'
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
        '(that’s a <a href="/corrections.html">correction</a>) but "your method picks '
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
        '<p class="methodology-back"><a href="/">← back to today</a></p>'
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
            f'<td class="archive-date"><a href="/{_e(date_str)}/">{_e(date_str)}</a></td>'
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
        '<p class="archive-back"><a href="/">← back to today</a></p>'
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
        '<a href="/methodology/">methodology</a>'
        '<a href="/corrections.html">corrections</a>'
        '<a href="/archive/">archive</a>'
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
  <link rel="stylesheet" href="/styles.css">
</head>
<body class="{_e(body_class)}">
<main class="{_e(main_class)}">{main_content}</main>
{footer}
<script src="/app.js" defer></script>
</body>
</html>
'''
