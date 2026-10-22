// Claude usage is drawable only when both meters carry a finite pct and a valid resetsAt.
function meterOk(m) {
  return !!m && typeof m.pct === 'number' && Number.isFinite(m.pct)
    && Number.isFinite(new Date(m.resetsAt).getTime());
}

export function usableUsage(usage) {
  return !!usage && meterOk(usage.session) && meterOk(usage.weekly);
}
