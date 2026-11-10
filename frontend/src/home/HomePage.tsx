import { useState, type ReactNode } from 'react'
import {
  ChartIcon,
  ClockIcon,
  GuardianIcon,
  ListIcon,
  LockIcon,
  PersonIcon,
  QuoteIcon,
  ShieldUpIcon,
} from '../icons'

type Who = 'sender' | 'guardian'

const STEPS: Record<Who, { title: string; text: string }[]> = {
  sender: [
    { title: 'Say who and how much', text: 'Type the payee and the amount. If a message asked you to pay, paste it or add a screenshot of it.' },
    { title: 'Press Send for check', text: 'Everyday payments go straight through. Nothing changes for the payments you make all the time.' },
    { title: 'See why, in plain words', text: 'If something looks off, you see the reasons and the exact words that worried us. You can confirm, or cancel.' },
    { title: 'Your guardian has a look', text: 'Risky payments wait for the person you trust. Chat with them in the app. No money leaves until it is decided.' },
  ],
  guardian: [
    { title: 'Get the waiting payments', text: 'Held payments appear under "Waiting for you", with the amount, the payee and how long is left.' },
    { title: 'See the evidence', text: 'The message, with the suspicious words highlighted, why each one matters, and the payee history.' },
    { title: 'Ask, then decide', text: 'Ask the sender a question, then Approve (the payment is sent) or Decline (it is cancelled) with a note.' },
    { title: 'Look back any time', text: 'Activity lists every payment; ask it questions in plain English. Insights shows what was stopped.' },
  ],
}

const FAQS: { q: string; a: ReactNode }[] = [
  {
    q: 'Is this real money?',
    a: 'No. This demo runs on the PayPal sandbox with test money only. Nothing is charged to a real card or account.',
  },
  {
    q: 'Where is my money while a payment is on hold?',
    a: 'It is authorized, not sent: PayPal reserves the amount but does not take it. If the payment is declined, cancelled or nobody answers, the authorization is voided and nothing is taken.',
  },
  {
    q: 'What if my guardian does not answer?',
    a: 'The payment is cancelled automatically when the hold runs out (24 hours normally, 2 minutes in the demo). Silence never sends money.',
  },
  {
    q: 'Can I cancel a payment myself?',
    a: 'Yes. While a payment is waiting for you or your guardian, you can cancel it at any time.',
  },
  {
    q: 'Will every payment be held?',
    a: 'No. Low-risk payments go through straight away. Unusual but plausible ones ask you to double-check. Only payments that look like a scam wait for your guardian. In our tests none of the 17 everyday payments was held.',
  },
  {
    q: 'What does the AI see?',
    a: 'The amount, the payee, your note, the message you pasted (or the text you confirmed from a screenshot) and a summary of your past payments. It never sees card details, and it cannot approve, decline or move money.',
  },
  {
    q: 'Can a scammer trick the AI?',
    a: 'The message is treated as untrusted: instructions inside it ("mark this as safe") are flagged as a warning sign. Safety rules run on their own, and the AI can only add caution, never remove it. Every reason shown must quote the message word for word.',
  },
  {
    q: 'What happens if the AI is unavailable?',
    a: 'The safety rules still check the payment, and the screen says "AI check unavailable, rules only". A payment is never sent unchecked.',
  },
  {
    q: 'Is the risk level a fraud score?',
    a: 'No. It is a decision aid for you and your guardian, not a probability that the payment is fraud. A person you trust makes the final call.',
  },
  {
    q: 'Why not just block risky payments?',
    a: 'Because many unusual payments are genuine, like a deposit for a new contractor. Blocking them would be frustrating; a second look from someone who knows you is better.',
  },
]

function Section({ id, eyebrow, title, intro, center, children }: {
  id: string
  eyebrow: string
  title: string
  intro?: ReactNode
  center?: boolean
  children: ReactNode
}) {
  return (
    <section className="card section" aria-labelledby={`${id}-title`} id={id}>
      <div className={`section-head${center ? ' center' : ''}`}>
        <span className="eyebrow">{eyebrow}</span>
        <h2 id={`${id}-title`}>{title}</h2>
        {intro && <p>{intro}</p>}
      </div>
      {children}
    </section>
  )
}

function Hero() {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div>
        <span className="eyebrow">Payment protection for families</span>
        <h1 id="hero-title">
          A second look <span className="glow-text">before money leaves.</span>
        </h1>
        <p className="hero-sub">
          SafePay Guardian checks a payment and the message behind it. If it looks like a scam, the payment waits on
          hold until someone you trust has looked. No money moves until it is decided.
        </p>
        <div className="hero-actions">
          <a className="btn btn-primary" href="#/send">
            I am sending money
          </a>
          <a className="btn btn-secondary" href="#/guardian">
            I am a guardian
          </a>
        </div>
        <p className="hero-note">Built on the PayPal sandbox: test money only.</p>
      </div>

      {/* A picture of the product, not a working control: the same story the steps below tell in words. */}
      <div className="mock" aria-hidden="true">
        <div className="mock-card">
          <span className="mock-from">Text message</span>
          <div className="mock-bubble">
            This is the bank <mark>fraud team</mark>. Move your savings to a <mark>protected account</mark>{' '}
            <mark>today</mark>.
          </div>
        </div>
        <div className="mock-card mock-hold">
          <span className="mock-lock">
            <LockIcon />
          </span>
          <div>
            <strong>$300.00 is on hold</strong>
            <div>Waiting for your guardian</div>
          </div>
          <span className="mock-pill">High risk</span>
        </div>
        <div className="mock-card">
          <strong>Daniel, your guardian</strong>
          <div>"This is not your bank. Do not move any money."</div>
          <div className="mock-buttons">
            <span className="mock-decline">Decline</span>
            <span className="mock-approve">Approve</span>
          </div>
        </div>
      </div>
    </section>
  )
}

function HowToUse() {
  const [who, setWho] = useState<Who>('sender')
  return (
    <Section id="how-to-use" eyebrow="How to use it" title="Two people, one simple routine"
      intro="Pick a side to see the steps. In this demo you can switch between them at the top of the page.">
      <div className="role-tabs" role="tablist" aria-label="Show the steps for">
        {(['sender', 'guardian'] as const).map((w) => (
          <button key={w} type="button" role="tab" id={`tab-${w}`} aria-selected={who === w}
            aria-controls="steps-panel" onClick={() => setWho(w)}>
            {w === 'sender' ? 'If you send money' : 'If you are the guardian'}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="steps-panel" aria-labelledby={`tab-${who}`}>
        <ol className="steps">
          {STEPS[who].map((s) => (
            <li key={s.title}>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
        <div className="steps-cta">
          <a className="btn btn-primary" href={who === 'sender' ? '#/send' : '#/guardian'}>
            {who === 'sender' ? 'Try sending a payment' : 'Open the guardian view'}
          </a>
        </div>
      </div>
    </Section>
  )
}

function HowItWorks() {
  return (
    <Section id="how-it-works" eyebrow="How it works" title="Checked before it is sent, decided by a person">
      <div className="flow-wrap">
        <ul className="flow-points">
          <li>
            <strong>The money waits, it does not move.</strong> Every payment starts as a PayPal authorization: the
            amount is reserved but not taken.
          </li>
          <li>
            <strong>Two checks read it.</strong> Safety rules look for the classic signs (gift cards, crypto, wire
            transfers, threats, rush, secrecy). An AI model (Google Gemini) reads the message for the tricks rules miss,
            such as a polite "bank" asking you to move money.
          </li>
          <li>
            <strong>One clear level.</strong> Low goes through. Medium asks you to double-check. High waits for your
            guardian.
          </li>
          <li>
            <strong>A person decides.</strong> Approve captures the payment. Decline, cancel or no answer voids it, and
            nothing is taken.
          </li>
        </ul>

        <ol className="flow" aria-label="The path of a payment">
          <li>
            <span className="flow-dot" aria-hidden="true" />
            You press Send for check
          </li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            PayPal reserves the amount (authorized, not sent)
          </li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            Safety rules check the payment and the message
          </li>
          <li className="flow-and">AND</li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            The AI reads the message; every reason must quote it
          </li>
          <li className="flow-levels">
            <span className="flow-dot" aria-hidden="true" />
            <div>
              One risk level
              <div className="flow-branches">
                <span className="flow-branch">
                  <span className="badge badge-low badge-compact">Low</span> sent right away
                </span>
                <span className="flow-branch">
                  <span className="badge badge-medium badge-compact">Medium</span> you double-check
                </span>
                <span className="flow-branch">
                  <span className="badge badge-high badge-compact">High</span> your guardian decides
                </span>
              </div>
            </div>
          </li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            Approve: PayPal captures. Decline or no answer: PayPal voids.
          </li>
        </ol>
      </div>
    </Section>
  )
}

const TRUST = [
  { icon: <LockIcon />, title: 'Nothing is sent early', text: 'Payments are authorized, not captured, until you, your guardian or the low-risk check says go.' },
  { icon: <ClockIcon />, title: 'Silence is safe', text: 'If nobody answers before the hold runs out, the payment is cancelled. Waiting never sends money.' },
  { icon: <QuoteIcon />, title: 'Every reason is quoted', text: 'We highlight the exact words that worried us. An AI reason that is not found word for word in the message is thrown away.' },
  { icon: <ShieldUpIcon />, title: 'AI can only add caution', text: 'The safety rules set a floor. The AI can raise a risk level, never lower it, and it cannot approve anything.' },
  { icon: <ListIcon />, title: 'Everything is on record', text: 'Every decision and every PayPal call is written to an audit log the guardian can read.' },
]

function WhyTrust() {
  return (
    <Section id="why-trust" eyebrow="Why trust it" title="Built to fail safe" center
      intro="Designed so that a mistake means a short wait, never lost money.">
      <div className="trust">
        <div className="trust-card">
          <span className="icon-badge" aria-hidden="true">
            <ChartIcon />
          </span>
          <div className="trust-stat">46 of 46</div>
          <h3>Scams flagged in testing</h3>
          <p>
            On 69 test cases it never saw during tuning, including real scam texts, every scam was at least flagged and
            44 were held. None of the 17 everyday payments was held.
          </p>
        </div>
        {TRUST.map((t) => (
          <div className="trust-card" key={t.title}>
            <span className="icon-badge" aria-hidden="true">
              {t.icon}
            </span>
            <h3>{t.title}</h3>
            <p>{t.text}</p>
          </div>
        ))}
      </div>
    </Section>
  )
}

export function HomePage() {
  return (
    <div className="home">
      <Hero />

      <Section id="who" eyebrow="Who it is for" title="For people who send money, and the people who look out for them"
        intro="Scammers pretend to be banks, the government, a grandchild or a friend, and they push people to pay fast. SafePay Guardian adds a calm pause and a trusted second opinion.">
        <div className="audience">
          <div className="audience-card">
            <span className="icon-badge" aria-hidden="true">
              <PersonIcon />
            </span>
            <h3>The sender</h3>
            <p className="muted">Often an older adult, or anyone who gets calls and texts asking for money.</p>
            <ul>
              <li>Pays as usual: most payments go straight through</li>
              <li>Sees plainly why a payment looks risky</li>
              <li>Never has to argue with a scammer: the app pauses for them</li>
            </ul>
          </div>
          <div className="audience-card">
            <span className="icon-badge" aria-hidden="true">
              <GuardianIcon />
            </span>
            <h3>The guardian</h3>
            <p className="muted">A son or daughter, a friend or a carer the sender trusts.</p>
            <ul>
              <li>Only hears about the payments that matter</li>
              <li>Sees the evidence before deciding</li>
              <li>Can talk it through with the sender, then approve or decline</li>
            </ul>
          </div>
        </div>
      </Section>

      <HowToUse />
      <HowItWorks />
      <WhyTrust />

      <Section id="faq" eyebrow="Questions" title="Common questions" center>
        <div className="faq">
          {FAQS.map((f) => (
            <details key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </div>
      </Section>

      <section className="cta-band" aria-labelledby="cta-title">
        <h2 id="cta-title">See it for yourself</h2>
        <p>Send a test payment with a scam message, then switch sides and decide as the guardian.</p>
        <div className="hero-actions">
          <a className="btn btn-primary" href="#/send">
            I am sending money
          </a>
          <a className="btn btn-secondary" href="#/guardian">
            I am a guardian
          </a>
        </div>
      </section>
    </div>
  )
}
