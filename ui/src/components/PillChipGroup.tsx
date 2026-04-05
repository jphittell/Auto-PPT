interface PillChipGroupProps {
  options: string[]
  value: string
  onChange: (value: string) => void
}

export function PillChipGroup({ options, value, onChange }: PillChipGroupProps) {
  return (
    <div className="flex flex-wrap gap-3">
      {options.map((option) => {
        const selected = option === value
        return (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`rounded-full px-4 py-2 text-sm transition ${
              selected ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50'
            }`}
          >
            {option}
          </button>
        )
      })}
    </div>
  )
}
