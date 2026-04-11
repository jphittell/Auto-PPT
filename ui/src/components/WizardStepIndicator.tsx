const steps = ['Upload', 'Prompt', 'Review outline', 'Generate']

export function WizardStepIndicator({ step }: { step: 1 | 2 | 3 | 4 }) {
  return (
    <ol className="grid gap-3 sm:grid-cols-4">
      {steps.map((label, index) => {
        const position = index + 1
        const status =
          position < step
            ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
            : position === step
              ? 'border-indigo-500 bg-indigo-50 text-indigo-900'
              : 'border-slate-200 bg-white text-slate-500'
        return (
          <li
            key={label}
            className={`rounded-2xl border px-4 py-3 text-sm ${status}`}
            aria-current={position === step ? 'step' : undefined}
          >
            <div className="font-medium">Step {position}</div>
            <div>{label}</div>
          </li>
        )
      })}
    </ol>
  )
}
