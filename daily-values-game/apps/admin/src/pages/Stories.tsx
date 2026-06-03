import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { StoryListItem } from "../lib/types";

const STATUSES = ["", "draft", "scheduled", "live", "archived"];

export default function Stories() {
  const [rows, setRows] = useState<StoryListItem[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.stories(status || undefined).then(setRows);
  }, [status]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Stories</h2>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "all"}
            </option>
          ))}
        </select>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">No stories.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1">Date</th>
              <th>Title</th>
              <th>Status</th>
              <th>Gates</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className="border-t border-slate-800">
                <td className="py-2">{s.publish_date ?? "—"}</td>
                <td>
                  <Link to={`/story/${s.id}`} className="hover:underline">
                    {s.title}
                  </Link>
                </td>
                <td>{s.status}</td>
                <td>{s.gate_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
