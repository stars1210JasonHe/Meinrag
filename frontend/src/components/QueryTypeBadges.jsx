import { useTranslation } from 'react-i18next'

const TYPE_COLORS = {
  fact: 'hsl(168 84% 40%)',
  overview: 'hsl(250 80% 65%)',
  reference: 'hsl(45 93% 47%)',
  exploratory: 'hsl(199 89% 48%)',
}

export default function QueryTypeBadges({ types }) {
  const { t, i18n } = useTranslation()
  if (!types || types.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1">
      {types.map(type => (
        <span
          key={type}
          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{ backgroundColor: TYPE_COLORS[type] ?? 'hsl(217 33% 17%)', color: '#fff' }}
        >
          {i18n.exists(`queryType.${type}`) ? t(`queryType.${type}`) : type}
        </span>
      ))}
    </div>
  )
}
