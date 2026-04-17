const TIER_STYLES = {
  high: { bg: 'hsl(142 72% 45%)', label: 'High confidence' },
  moderate: { bg: 'hsl(38 92% 50%)', label: 'Moderate confidence' },
  low: { bg: 'hsl(0 72% 55%)', label: 'Low confidence' },
}

export default function ConfidenceBadge({ tier }) {
  if (!tier) return null
  const style = TIER_STYLES[tier] ?? TIER_STYLES.low
  return (
    <span
      className="px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{ backgroundColor: style.bg, color: '#fff' }}
    >
      {style.label}
    </span>
  )
}
