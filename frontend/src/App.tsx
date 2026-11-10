import { useEffect } from 'react'
import { GuardianArea } from './guardian/GuardianArea'
import { go, useHashRoute } from './hooks'
import { PaymentPage } from './sender/PaymentPage'
import { SendPage } from './sender/SendPage'

type Role = 'sender' | 'guardian'

function Header({ role, wide }: { role: Role; wide: string }) {
  return (
    <header className={`app-header role-${role}${wide}`}>
      <div className="app-header-inner">
        <a href="#/send" className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◆
          </span>
          SafePay Guardian
        </a>
        <span className="sandbox-label">Sandbox: test money only</span>
        <nav className="role-switch" aria-label="Choose who you are">
          <button type="button" aria-pressed={role === 'sender'} onClick={() => go('/send')}>
            I am the sender
          </button>
          <button type="button" aria-pressed={role === 'guardian'} onClick={() => go('/guardian')}>
            I am the guardian
          </button>
        </nav>
      </div>
    </header>
  )
}

export default function App() {
  const [section = 'send', ...rest] = useHashRoute()
  const id = rest[0]
  const role: Role = section === 'guardian' ? 'guardian' : 'sender'
  const path = rest.join('/')
  const wide = role === 'guardian' && rest[0] === 'activity' ? ' wide' : ''

  useEffect(() => {
    document.title = role === 'guardian' ? 'SafePay Guardian · Guardian' : 'SafePay Guardian · Send money'
    window.scrollTo(0, 0)
  }, [role, path])

  return (
    <>
      <Header role={role} wide={wide} />
      <main className={`app-main role-${role}${wide}`}>
        {section === 'guardian' ? <GuardianArea parts={rest} /> : id ? <PaymentPage key={id} id={id} /> : <SendPage />}
      </main>
      <footer className={`app-footer role-${role}${wide}`}>
        Demo of a protection workflow on the PayPal sandbox. The risk level is a decision aid, not a fraud
        probability. There is no real login.
      </footer>
    </>
  )
}
