import { api } from "../lib/api";

// The share card is the growth engine — first-class from day one (§1, §10).
// The actual shareable image is SERVER-rendered (spoiler-free PNG with a tiny
// legend, see api/src/share-card.ts). This component just previews it and wires
// the native share sheet.
export function ShareCard({ storyId, title }: { storyId: string; title: string }) {
  const url = api.shareCardUrl(storyId);

  async function share() {
    const shareUrl = `${window.location.origin}/?s=${storyId}`;
    if (navigator.share) {
      await navigator.share({ title: "Daily Values", text: title, url: shareUrl });
    } else {
      await navigator.clipboard.writeText(shareUrl);
    }
  }

  return (
    <div className="space-y-3">
      <img
        src={url}
        alt="Today's values strip (spoiler-free)"
        className="w-full rounded-xl border border-slate-800"
        loading="lazy"
      />
      <button
        onClick={share}
        className="w-full rounded-xl bg-slate-100 px-4 py-3 font-medium text-slate-900 hover:bg-white"
      >
        Share today's story
      </button>
    </div>
  );
}
