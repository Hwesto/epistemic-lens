import { ImageResponse } from "@vercel/og";
import type { VercelRequest } from "@vercel/node";

export const config = { runtime: "edge" };

// The growth engine (§1, §10): a SERVER-rendered, spoiler-free PNG with a tiny
// legend (the colours aren't self-explanatory the way Wordle's win-state is).
// It shows the day's "values strip" — the axis palette — and the date/title,
// never the outcome of any choice.
const AXIS_COLORS = ["#ef4444", "#f59e0b", "#eab308", "#22c55e", "#3b82f6", "#a855f7"];
const AXIS_LABELS = ["Care", "Equality", "Proportion", "Loyalty", "Authority", "Purity"];

export default async function handler(req: VercelRequest) {
  const { searchParams } = new URL(req.url ?? "", "http://localhost");
  const title = searchParams.get("title") ?? "Today's dilemma";
  const date = searchParams.get("date") ?? "";

  return new ImageResponse(
    {
      type: "div",
      props: {
        style: {
          width: "1200px",
          height: "630px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0f172a",
          color: "#f1f5f9",
          padding: "64px",
          fontFamily: "sans-serif",
        },
        children: [
          {
            type: "div",
            props: {
              style: { fontSize: 28, color: "#94a3b8" },
              children: `Daily Values · ${date}`,
            },
          },
          {
            type: "div",
            props: {
              style: { fontSize: 64, fontWeight: 700, lineHeight: 1.1 },
              children: title,
            },
          },
          // the coloured strip (spoiler-free)
          {
            type: "div",
            props: {
              style: { display: "flex", gap: "12px" },
              children: AXIS_COLORS.map((c) => ({
                type: "div",
                props: { style: { flex: 1, height: "40px", borderRadius: "8px", background: c } },
              })),
            },
          },
          // tiny legend
          {
            type: "div",
            props: {
              style: { display: "flex", gap: "24px", fontSize: 20, color: "#cbd5e1" },
              children: AXIS_LABELS.map((label, i) => ({
                type: "div",
                props: {
                  style: { display: "flex", alignItems: "center", gap: "8px" },
                  children: [
                    {
                      type: "div",
                      props: {
                        style: {
                          width: "14px",
                          height: "14px",
                          borderRadius: "4px",
                          background: AXIS_COLORS[i],
                        },
                      },
                    },
                    { type: "div", props: { children: label } },
                  ],
                },
              })),
            },
          },
        ],
      },
      // @vercel/og renders this plain-element object at runtime; its type wants a
      // ReactElement, so cast rather than pull JSX tooling into one server file.
    } as any,
    { width: 1200, height: 630 }
  );
}
