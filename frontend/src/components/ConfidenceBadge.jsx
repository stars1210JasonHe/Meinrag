import { useTranslation } from 'react-i18next'

const TIER_BG = {
  high: 'hsl(142 72% 45%)',
  moderate: 'hsl(38 92% 50%)',
  low: 'hsl(0 72% 55%)',
}

export default function ConfidenceBadge({ tier }) {
  const { t } = useTranslation()
  if (!tier) return null
  const bg = TIER_BG[tier] ?? TIER_BG.low
  const label = t(`confidence.${tier in TIER_BG ? tier : 'low'}`)
  return (
    <span
      className="px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{ backgroundColor: bg, color: '#fff' }}
    >
      {label}
    </span>
  )
}
