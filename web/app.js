// epistemic-lens / daily framings — landing page client
//
// Fetches /latest.json + per-story analysis.json (lazy on expand) and
// renders the daily front page. No frameworks, no build step. The
// hero-pick logic mirrors render_thread.py:_build_hook so the front
// page leads with the same finding the social drafts lead with.

(() => {
  const cache = new Map(); // analysis_url -> parsed JSON

  // ---------- helpers ----------

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const escape = (s) => String(s ?? "").replace(/[&<>]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  async function fetchJSON(url) {
    if (cache.has(url)) return cache.get(url);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
    const j = await res.json();
    cache.set(url, j);
    return j;
  }

  function fmtNumber(n) {
    return Number.isFinite(n) ? n.toLocaleString() : String(n ?? "?");
  }

  // ---------- hero pick (same priority order as render_thread.py) ----------

  function pickHero(analyses) {
    // analyses: [{ analysis, briefing }] (briefing optional)
    // priority 1: any story with a paradox -> the most striking one
    const withParadox = analyses.filter(a => a.analysis?.paradox);
    if (withParadox.length) {
      const a = withParadox[0].analysis;
      return {
        kind: "paradox",
        eyebrow: "the paradox",
        text: a.paradox.joint_conclusion,
        attr: `${a.paradox.a.outlet} (${a.paradox.a.bucket}) & ${a.paradox.b.outlet} (${a.paradox.b.bucket}) — ${a.story_title}`,
      };
    }
    // priority 2: strongest isolation outlier (mean_similarity < 0.30 for LaBSE cosine)
    const isoSorted = analyses
      .map(a => ({ a, top: a.analysis?.isolation_top?.[0] }))
      .filter(x => x.top && x.top.mean_similarity < 0.30)
      .sort((x, y) => x.top.mean_similarity - y.top.mean_similarity);
    if (isoSorted.length) {
      const { a, top } = isoSorted[0];
      return {
        kind: "isolation",
        eyebrow: "isolation outlier",
        text: `${a.analysis.n_buckets} outlets covered ${a.analysis.story_title}. ${top.bucket} diverged most from the rest. (mean_similarity ${top.mean_similarity})`,
        attr: top.note || "",
      };
    }
    // priority 3: bucket-exclusive vocab from any story
    for (const x of analyses) {
      const v = x.analysis?.exclusive_vocab_highlights?.[0];
      if (v && v.terms?.length) {
        return {
          kind: "vocab",
          eyebrow: "uniquely said",
          text: `On ${x.analysis.story_title}, only ${v.bucket} said: ${v.terms.slice(0, 3).map(t => `"${t}"`).join(", ")}.`,
          attr: v.what_it_reveals || "",
        };
      }
    }
    // priority 4: generic structural lead
    if (analyses.length) {
      const a = analyses[0].analysis;
      return {
        kind: "generic",
        eyebrow: "today",
        text: `${analyses.length} ${analyses.length === 1 ? "story" : "stories"} covered today. Top: ${a.story_title} — ${a.n_buckets} buckets, ${a.n_articles} articles, ${a.frames?.length ?? 0} frames.`,
        attr: "",
      };
    }
    return null;
  }

  function renderHero(hero) {
    const root = $("#hero");
    root.removeAttribute("aria-busy");
    if (!hero) {
      root.innerHTML = `<p class="hero-loading">No stories yet for today. Check back at 07:00 UTC.</p>`;
      return;
    }
    root.innerHTML = `
      <span class="hero-eyebrow">${escape(hero.eyebrow)}</span>
      <p class="hero-text">${escape(hero.text)}</p>
      ${hero.attr ? `<p class="hero-attribution"><span class="out">${escape(hero.attr)}</span></p>` : ""}
    `;
  }

  // ---------- meta strip + footer ----------

  function renderMeta(latest) {
    const strip = $("#meta-strip");
    const date = latest?.date || "—";
    const n = latest?.n_stories ?? 0;
    strip.innerHTML = `
      <span class="pill">${escape(date)}</span>
      <span class="pill">${n} ${n === 1 ? "story" : "stories"}</span>
      ${latest?.meta_version ? `<span class="pill">meta-v${escape(latest.meta_version)}</span>` : ""}
    `;
    const fm = $("#footer-meta");
    fm.textContent = `methodology pin: meta-v${latest?.meta_version || "?"}`;
    if (latest?.date) {
      $("#footer-latest").href = `${latest.date}/index.json`;
    }
  }

  // ---------- card rendering ----------

  function cardLinkUrl(date, key, artifact) {
    switch (artifact) {
      case "analysis_md":   return `${date}/${key}/analysis.md`;
      case "analysis_json": return `${date}/${key}/analysis.json`;
      case "thread":        return `${date}/${key}/thread.json`;
      case "carousel":      return `${date}/${key}/carousel.json`;
      case "long":          return `${date}/${key}/long.json`;
    }
    return "#";
  }

  function renderCard(analysis, date) {
    const tpl = $("#story-card-tpl");
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.storyKey = analysis.story_key;

    $(".card-title", node).textContent = analysis.story_title;
    $('[data-field="n_buckets"]', node).textContent = `${analysis.n_buckets} buckets`;
    $('[data-field="n_articles"]', node).textContent = `${analysis.n_articles} articles`;

    if (analysis.paradox) {
      $(".paradox-badge", node).hidden = false;
    }

    $(".card-tldr", node).textContent = analysis.tldr || "";

    $$('[data-artifact]', node).forEach(a => {
      a.href = cardLinkUrl(date, analysis.story_key, a.dataset.artifact);
    });

    const detailBody = $(".card-detail-body", node);
    detailBody.dataset.status = "ready";
    detailBody.append(buildDetail(analysis));

    return node;
  }

  function buildDetail(a) {
    const frag = document.createDocumentFragment();

    // Frame matrix
    if (a.frames?.length) {
      const allBuckets = Array.from(
        new Set(a.frames.flatMap(f => f.buckets || []))
      ).sort();
      const table = document.createElement("table");
      table.className = "matrix";
      const head = document.createElement("tr");
      head.appendChild(thEl("Bucket", "bucket"));
      a.frames.forEach((f, i) => head.appendChild(thEl(short(f.label, 14), "frame", f.label)));
      table.appendChild(head);
      allBuckets.forEach(b => {
        const row = document.createElement("tr");
        row.appendChild(tdEl(b, "bucket"));
        a.frames.forEach(f => {
          const on = (f.buckets || []).includes(b);
          row.appendChild(tdEl(on ? "✕" : "·", on ? "on" : "off"));
        });
        table.appendChild(row);
      });
      const sect = section("Frame matrix");
      sect.appendChild(table);
      frag.appendChild(sect);
    }

    // Isolation
    if (a.isolation_top?.length) {
      const sect = section("Most isolated");
      const ul = document.createElement("ul");
      ul.className = "isolation-list";
      a.isolation_top.slice(0, 6).forEach(r => {
        const li = document.createElement("li");
        li.className = "iso-pill";
        li.innerHTML = `<span>${escape(r.bucket)}</span><span class="num">${r.mean_similarity}</span>`;
        ul.appendChild(li);
      });
      sect.appendChild(ul);
      frag.appendChild(sect);
    }

    // Exclusive vocab
    if (a.exclusive_vocab_highlights?.length) {
      const sect = section("Bucket-exclusive vocabulary");
      a.exclusive_vocab_highlights.forEach(h => {
        const block = document.createElement("div");
        block.className = "vocab-block";
        const head = document.createElement("h4");
        head.textContent = `${h.bucket}${h.what_it_reveals ? " — " + h.what_it_reveals : ""}`;
        block.appendChild(head);
        const tags = document.createElement("div");
        tags.className = "tags";
        (h.terms || []).slice(0, 8).forEach(t => {
          const sp = document.createElement("span");
          sp.className = "tag";
          sp.textContent = t;
          tags.appendChild(sp);
        });
        block.appendChild(tags);
        sect.appendChild(block);
      });
      frag.appendChild(sect);
    }

    // Paradox split
    if (a.paradox) {
      const sect = section("Paradox");
      const block = document.createElement("div");
      block.className = "paradox-block";
      block.innerHTML = `
        <div class="paradox-side">
          <blockquote>${escape(a.paradox.a.quote)}</blockquote>
          <div class="paradox-attr">— ${escape(a.paradox.a.outlet)} (${escape(a.paradox.a.bucket)})</div>
        </div>
        <div class="paradox-side">
          <blockquote>${escape(a.paradox.b.quote)}</blockquote>
          <div class="paradox-attr">— ${escape(a.paradox.b.outlet)} (${escape(a.paradox.b.bucket)})</div>
        </div>
        <div class="paradox-conclusion">${escape(a.paradox.joint_conclusion)}</div>`;
      sect.appendChild(block);
      frag.appendChild(sect);
    }

    // Bottom line
    if (a.bottom_line) {
      const sect = section("Bottom line");
      const p = document.createElement("p");
      p.className = "detail-tldr";
      p.textContent = a.bottom_line;
      sect.appendChild(p);
      frag.appendChild(sect);
    }

    return frag;
  }

  function section(title) {
    const s = document.createElement("section");
    s.className = "detail-section";
    const h = document.createElement("h3");
    h.textContent = title;
    s.appendChild(h);
    return s;
  }

  function thEl(text, cls, title) {
    const th = document.createElement("th");
    th.className = cls;
    th.textContent = text;
    if (title) th.title = title;
    return th;
  }
  function tdEl(text, cls) {
    const td = document.createElement("td");
    td.className = cls;
    td.textContent = text;
    return td;
  }
  function short(s, n) { return s.length <= n ? s : s.slice(0, n - 1) + "…"; }

  // ---------- main ----------

  async function main() {
    let latest;
    try {
      latest = await fetchJSON("latest.json");
    } catch (e) {
      $("#hero").innerHTML = `<p class="hero-loading">Couldn't load <code>latest.json</code>: ${escape(e.message)}.</p>`;
      $("#stories").innerHTML = "";
      return;
    }
    renderMeta(latest);

    if (!latest?.date) {
      $("#hero").innerHTML = `<p class="hero-loading">No date in latest.json. Pipeline may not have produced today's data yet.</p>`;
      $("#stories").innerHTML = "";
      return;
    }

    let dateIndex;
    try {
      dateIndex = await fetchJSON(`${latest.date}/index.json`);
    } catch (e) {
      $("#hero").innerHTML = `<p class="hero-loading">Couldn't load <code>${latest.date}/index.json</code>: ${escape(e.message)}.</p>`;
      $("#stories").innerHTML = "";
      return;
    }

    const stories = dateIndex.stories || [];
    // For each story that has analysis_json, fetch it. Skip stories without one.
    const analysisFetches = stories
      .filter(s => s.has?.analysis_json)
      .map(s => fetchJSON(`${latest.date}/${s.key}/analysis.json`).then(a => ({ analysis: a, story: s })));

    const results = await Promise.allSettled(analysisFetches);
    const analyses = results.filter(r => r.status === "fulfilled").map(r => r.value);

    renderHero(pickHero(analyses));

    const grid = $("#stories");
    grid.removeAttribute("aria-busy");
    grid.innerHTML = "";
    if (!analyses.length) {
      grid.innerHTML = `<div class="loader">No stories with analyses yet for ${escape(latest.date)}.</div>`;
      return;
    }
    analyses.forEach(({ analysis }) => {
      grid.appendChild(renderCard(analysis, latest.date));
    });
  }

  document.addEventListener("DOMContentLoaded", main);
})();
