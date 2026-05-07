// TikTok-style burned-in captions. Splits the scene's voiceover text
// into ~6-9-word chunks and shows each chunk for its proportional
// fraction of the scene duration. Positioned above the QuoteCard so
// they don't fight for attention.

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";

type Props = {
  voiceover: string;
  durationInFrames: number;
};

// Greedy chunker: target ~7 words per chunk, but break on punctuation
// to avoid awkward splits across clauses.
function chunkText(text: string, targetWords: number = 7): string[] {
  if (!text) return [];
  // Normalise whitespace
  const t = text.replace(/\s+/g, " ").trim();
  // Split into "phrases" by punctuation
  const phrases = t.split(/(?<=[.,;:!?])\s+/);
  const chunks: string[] = [];
  let buf: string[] = [];
  for (const phrase of phrases) {
    const words = phrase.split(" ");
    for (const w of words) {
      buf.push(w);
      // Break early if we hit ending punctuation, or reach target
      const isPunctEnd = /[.!?]$/.test(w);
      if (buf.length >= targetWords || isPunctEnd) {
        chunks.push(buf.join(" "));
        buf = [];
      }
    }
  }
  if (buf.length) chunks.push(buf.join(" "));
  return chunks;
}

export const Captions: React.FC<Props> = ({ voiceover, durationInFrames }) => {
  const frame = useCurrentFrame();
  const chunks = chunkText(voiceover);
  if (chunks.length === 0) return null;

  // Each chunk gets a proportional slice. Slight overlap (10% pre-pad)
  // ensures captions don't appear after the audio's already moved on.
  const perChunk = durationInFrames / chunks.length;
  const idx = Math.min(chunks.length - 1, Math.max(0, Math.floor(frame / perChunk)));
  const text = chunks[idx];

  // Subtle in-fade per chunk
  const localFrame = frame - idx * perChunk;
  const fade = Math.min(1, localFrame / 4);

  return (
    <div
      style={{
        position: "absolute",
        bottom: 580, // above QuoteCard (which sits at bottom: 200 + ~280 height)
        left: 60,
        right: 60,
        textAlign: "center",
        opacity: fade,
        pointerEvents: "none",
        zIndex: 25,
      }}
    >
      <div
        style={{
          display: "inline-block",
          background: "rgba(0,0,0,0.62)",
          padding: "16px 28px",
          borderRadius: 14,
          color: "white",
          fontFamily:
            "Inter, -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
          fontSize: 48,
          fontWeight: 800,
          letterSpacing: "0.005em",
          lineHeight: 1.18,
          textShadow:
            "0 2px 8px rgba(0,0,0,0.95), 0 0 2px rgba(0,0,0,1)",
          maxWidth: "95%",
          wordBreak: "break-word",
        }}
      >
        {text}
      </div>
    </div>
  );
};
