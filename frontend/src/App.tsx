import { useEffect } from 'react'
import { GuardianPage } from './guardian/GuardianPage'
import { go, useHashRoute } from './hooks'
import { PaymentPage } from './sender/PaymentPage'
import { SendPage } from './sender/SendPage'

type Role = 'sender' | 'guardian'

function Header({ role }: { role: Role }) {
  return (
    <header className="app-header">
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
  const [section = 'send', id] = useHashRoute()
  const role: Role = section === 'guardian' ? 'guardian' : 'sender'

  useEffect(() => {
    document.title = role === 'guardian' ? 'SafePay Guardian · Guardian' : 'SafePay Guardian · Send money'
    window.scrollTo(0, 0)
  }, [role, id])

  return (
    <>
      <Header role={role} />
      <main className={`app-main role-${role}`}>
        {section === 'guardian' ? <GuardianPage /> : id ? <PaymentPage key={id} id={id} /> : <SendPage />}
      </main>
      <footer className="app-footer">
        Demo of a protection workflow on the PayPal sandbox. The risk level is a decision aid, not a fraud
        probability. There is no real login.
      </footer>
    </>
  )
}
