// Small line icons drawn for this app (24px grid, currentColor), plus the brand mark.

import { useId, type ReactNode } from 'react'

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  )
}

export function BrandMark() {
  const id = useId()
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7b5cf5" />
          <stop offset=".55" stopColor="#c45ad9" />
          <stop offset="1" stopColor="#f08a4b" />
        </linearGradient>
      </defs>
      <path d="M16 2 4 6.5v8.2C4 22.3 9.1 28 16 30c6.9-2 12-7.7 12-15.3V6.5L16 2z" fill={`url(#${id})`} />
      <path d="m10.5 16.2 3.8 3.8 7.4-7.6" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round"
        strokeLinejoin="round" />
    </svg>
  )
}

export const SunIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Icon>
)

export const MoonIcon = () => (
  <Icon>
    <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z" />
  </Icon>
)

export const LockIcon = () => (
  <Icon>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
    <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    <path d="M12 14.5v2.5" />
  </Icon>
)

export const ClockIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Icon>
)

export const QuoteIcon = () => (
  <Icon>
    <path d="M4 5h16v10H9l-5 4z" />
    <path d="M8 9h8M8 12h5" />
  </Icon>
)

export const ShieldUpIcon = () => (
  <Icon>
    <path d="M12 3 5 6v5c0 4.6 3 8.3 7 10 4-1.7 7-5.4 7-10V6z" />
    <path d="m9 12 3-3 3 3M12 9v7" />
  </Icon>
)

export const ChartIcon = () => (
  <Icon>
    <path d="M4 20V4M4 20h16" />
    <path d="M8 16v-4M12 16V8M16 16v-6" />
  </Icon>
)

export const ListIcon = () => (
  <Icon>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <circle cx="4.5" cy="6" r="1" />
    <circle cx="4.5" cy="12" r="1" />
    <circle cx="4.5" cy="18" r="1" />
  </Icon>
)

export const PersonIcon = () => (
  <Icon>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Icon>
)

export const GuardianIcon = () => (
  <Icon>
    <path d="M12 3 5 6v5c0 4.6 3 8.3 7 10 4-1.7 7-5.4 7-10V6z" />
    <circle cx="12" cy="10" r="2.5" />
    <path d="M8.5 16a4 4 0 0 1 7 0" />
  </Icon>
)
