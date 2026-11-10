import { useEffect } from 'react'
import { GuardianArea } from './guardian/GuardianArea'
import { HomePage } from './home/HomePage'
import { go, useHashRoute } from './hooks'
import { BrandMark, MoonIcon, SunIcon } from './icons'
import { PaymentPage } from './sender/PaymentPage'
import { SendPage } from './sender/SendPage'
import { setTheme, useTheme } from './theme'

type Role = 'home' | 'sender' | 'guardian'

function ThemeToggle() {
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(next)}
      aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}>
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}

function Header({ role, wide }: { role: Role; wide: string }) {
  return (
    <header className={`app-header role-${role}${wide}`}>
      <div className="app-header-inner">
        <a href="#/" className="brand" aria-label="SafePay Guardian, home">
          <BrandMark />
          SafePay Guardian
        </a>
        <span className="sandbox-label" title="PayPal sandbox: no real money moves" aria-label="PayPal sandbox: test money only">
          Test money only
        </span>
        <nav className="role-switch" aria-label="Choose who you are">
          <button type="button" aria-pressed={role === 'sender'} onClick={() => go('/send')}>
            I am the sender
          </button>
          <button type="button" aria-pressed={role === 'guardian'} onClick={() => go('/guardian')}>
            I am the guardian
          </button>
        </nav>
        <ThemeToggle />
      </div>
    </header>
  )
}

const TITLES: Record<Role, string> = {
  home: 'SafePay Guardian · A second look before money leaves',
  sender: 'SafePay Guardian · Send money',
  guardian: 'SafePay Guardian · Guardian',
}

export default function App() {
  const [section = 'home', ...rest] = useHashRoute()
  const id = rest[0]
  const role: Role = section === 'guardian' ? 'guardian' : section === 'send' ? 'sender' : 'home'
  const path = rest.join('/')
  const wide = role === 'guardian' && rest[0] === 'activity' ? ' wide' : ''

  useEffect(() => {
    document.title = TITLES[role]
    window.scrollTo(0, 0)
  }, [role, path])

  return (
    <>
      <Header role={role} wide={wide} />
      <main className={`app-main role-${role}${wide}`}>
        {role === 'guardian' ? (
          <GuardianArea parts={rest} />
        ) : role === 'sender' ? (
          id ? <PaymentPage key={id} id={id} /> : <SendPage />
        ) : (
          <HomePage />
        )}
      </main>
      <footer className={`app-footer role-${role}${wide}`}>
        Demo of a protection workflow on the PayPal sandbox. The risk level is a decision aid, not a fraud
        probability. There is no real login.
      </footer>
    </>
  )
}
