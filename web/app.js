// The Same Story — minimal client JS
// ~50 lines. Only handles share / copy-link buttons and keyboard nav.
// All rendering is server-side via build_index.py at deploy time.

(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

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
