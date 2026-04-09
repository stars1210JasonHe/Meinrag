export default function CitationBadge({ num, onClick }) {
  return (
    <sup
      onClick={(e) => { e.stopPropagation(); onClick(num - 1) }}
      className="inline-flex items-center justify-center mx-0.5 px-1.5 py-0.5 rounded text-[11px] font-bold cursor-pointer select-none hover:brightness-150"
      style={{
        backgroundColor: 'hsl(250 80% 55% / 0.4)',
        color: 'hsl(210 40% 98%)',
        verticalAlign: 'super',
        lineHeight: 1,
        minWidth: '18px',
        textAlign: 'center',
      }}
      title={`Source [${num}]`}
    >
      {num}
    </sup>
  )
}
