interface ToneSliderProps {
  value: number
  onChange: (value: number) => void
}

export function ToneSlider({ value, onChange }: ToneSliderProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>Analytical</span>
        <span className="font-medium text-slate-900">{value}</span>
        <span>Bold</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-indigo-600"
      />
    </div>
  )
}
