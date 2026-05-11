// The Same Story — minimal client JS
//
// In the final design (PR D, post-merge) all rendering is server-side
// via build_index.py. Until that lands, this script hydrates the
// load-bearing card fields (eyebrow / headline / kicker / byline /
// see-how) from /today.json so the deployed site shows real data
// rather than the placeholder design-preview content baked into
// index.html. The archetype-specific .card-content body remains
// design-preview until PR D ships proper archetype renderers.

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  // ----- Hydrate the daily card from /today.json -----
  // Temporary bridge until build_index.py renders the card server-side
  // (PR D). Sets text on the load-bearing fields only; leaves the
  // archetype body alone.
  const ARCHETYPE_EYEBROWS = {
    word:    "Word · how each language named it",
    paradox: "Paradox · opposing blocs, same conclusion",
    silence: "Silence · who didn't cover it",
    shift:   "Shift · what moved this week",
    sources: "Sources · whose voices made the cut",
    tilt:    "Tilt · log-odds vs wire baseline",
    echo:    "Echo · who echoed whom, how late",
  };
  (async () => {
    try {
      const res = await fetch("/today.json", {cache: "no-cache"});
      if (!res.ok) return;
      const t = await res.json();
      const card = $(".card");
      if (card && t.card_kind) {
        card.dataset.cardKind = t.card_kind;
        card.classList.forEach((c) => {
          if (c.startsWith("card--")) card.classList.remove(c);
        });
        card.classList.add(`card--${t.card_kind}`);
      }
      const eyebrow = $(".card-eyebrow");
      if (eyebrow) eyebrow.textContent = ARCHETYPE_EYEBROWS[t.card_kind] || eyebrow.textContent;
      const headline = $(".card-headline");
      if (headline && t.headline) headline.textContent = t.headline;
      const kicker = $(".card-kicker");
      if (kicker && t.kicker) kicker.textContent = t.kicker;
      const seeHow = $(".card-byline .see-how, .see-how");
      if (seeHow && t.see_how_path) seeHow.setAttribute("href", t.see_how_path);
      const date = $(".card-brand time");
      if (date && t.date) {
        date.setAttribute("datetime", t.date);
        date.textContent = new Date(t.date).toLocaleDateString("en-GB",
          {day: "numeric", month: "long", year: "numeric"});
      }
    } catch (_) { /* offline / no today.json yet — keep placeholders */ }
  })();

  // ----- Share button -----
  const shareBtn = $('[data-action="share"]');
  if (shareBtn && navigator.share) {
    shareBtn.addEventListener("click", async () => {
      const eyebrow = $(".card-eyebrow")?.textContent?.trim() || "";
      const headline = $(".card-headline")?.textContent?.trim() || "";
      try {
        await navigator.share({
          title: "The Same Story",
          text: `${eyebrow}\n${headline}`,
          url: location.href,
        });
      } catch (_) { /* user cancelled */ }
    });
  } else if (shareBtn) {
    // Fallback for desktop: open a tweet intent
    shareBtn.addEventListener("click", () => {
      const headline = $(".card-headline")?.textContent?.trim() || "";
      const text = encodeURIComponent(`${headline} · via The Same Story`);
      const url = encodeURIComponent(location.href);
      window.open(`https://twitter.com/intent/tweet?text=${text}&url=${url}`,
                  "_blank", "noopener");
    });
  }

  // ----- Copy link -----
  const copyBtn = $('[data-action="copy-link"]');
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(location.href);
        const original = copyBtn.textContent;
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => { copyBtn.textContent = original; }, 1500);
      } catch (_) {
        copyBtn.textContent = "Press ⌘C";
      }
    });
  }

  // ----- Keyboard nav -----
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, [contenteditable]")) return;
    if (e.key === "ArrowLeft") {
      const prev = $('a[rel="prev"]'); if (prev) prev.click();
    }
    if (e.key === "ArrowRight") {
      const next = $('a[rel="next"]'); if (next) next.click();
    }
  });
})();
