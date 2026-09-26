/** Polygon per-ticker stream is down: the chart is frozen at its last bar (#388). */
export function LiveFeedUnavailableBadge() {
  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-amber-400 bg-amber-50 px-4 py-3 text-amber-800 dark:border-amber-500 dark:bg-amber-900/20 dark:text-amber-300"
    >
      <span className="mt-0.5 text-lg leading-none">⚠️</span>
      <div className="flex-1 text-sm">
        <span className="font-semibold">Live feed unavailable — showing last known data</span>. The Polygon
        real-time stream is disconnected; the chart resumes updating when it reconnects.
      </div>
    </div>
  );
}
