import { useRef, useState, type ReactNode } from 'react'
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
import { Shield, Story } from './HeroScene'
import { useCountUp, useInView, usePointerLook } from './motion'

type Who = 'sender' | 'guardian'

const STEPS: Record<Who, { title: string; text: string }[]> = {
  sender: [
    { title: 'Say who and how much', text: 'Paste the message you got, or add a screenshot.' },
    { title: 'Press Send for check', text: 'Everyday payments go straight through.' },
    { title: 'See why', text: 'The reasons, and the exact words that worried us.' },
    { title: 'Your guardian looks', text: 'Risky payments wait. No money leaves until decided.' },
  ],
  guardian: [
    { title: 'Get waiting payments', text: 'Amount, payee and time left.' },
    { title: 'See the evidence', text: 'Highlighted message and payee history.' },
    { title: 'Ask, then decide', text: 'Approve sends it. Decline cancels it.' },
    { title: 'Look back', text: 'Activity and Insights show what was stopped.' },
  ],
}

const FAQS: { q: string; a: ReactNode }[] = [
  { q: 'Is this real money?', a: 'No. It runs on the PayPal sandbox, with test money only.' },
  {
    q: 'Where is my money while a payment is on hold?',
    a: 'Reserved, not sent. If it is declined, cancelled or unanswered, it is released and nothing is taken. Your bank may take a few days to show the reservation as gone.',
  },
  {
    q: 'What if my guardian does not answer?',
    a: 'The payment is cancelled when the hold runs out (24 hours; 2 minutes in the demo).',
  },
  { q: 'Can I cancel a payment myself?', a: 'Yes, any time while it is waiting.' },
  {
    q: 'Will every payment be held?',
    a: 'No. Low risk goes through. Medium asks you to double-check. Only scam-like payments are held.',
  },
  {
    q: 'What does the AI see?',
    a: 'The amount, payee, note, message and past payments. A screenshot is sent to Google Gemini to be read. Never card details. It cannot move money.',
  },
  {
    q: 'Can a scammer trick the AI?',
    a: 'The message is treated as untrusted, and the AI can only add caution. Every reason must quote the message.',
  },
  {
    q: 'What if the AI is unavailable?',
    a: 'The safety rules still check the payment, and the screen says "rules only".',
  },
  {
    q: 'Is the risk level a fraud score?',
    a: 'No. It is a decision aid, not a probability. A person makes the call.',
  },
  {
    q: 'Why not just block risky payments?',
    a: 'Many unusual payments are genuine. A second look beats a block.',
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
  const ref = useRef<HTMLElement>(null)
  const seen = useInView(ref, 0.08)
  return (
    <section ref={ref} className={`card section reveal${seen ? ' in' : ''}`} aria-labelledby={`${id}-title`} id={id}>
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
  const heroRef = useRef<HTMLElement>(null)
  const visualRef = useRef<HTMLDivElement>(null)
  const tracking = usePointerLook(heroRef, visualRef)
  const [stage, setStage] = useState(0)
  return (
    <section className="hero" aria-labelledby="hero-title" ref={heroRef}>
      <div className="hero-copy">
        <span className="eyebrow">Payment protection for senders and guardians</span>
        <h1 id="hero-title" className="kinetic">
          <span className="line">
            <span>A second look</span>
          </span>{' '}
          <span className="line">
            <span className="glow-text">before money leaves.</span>
          </span>
        </h1>
        <p className="hero-lead">
          We check every payment and the message behind it. Risky ones wait for someone you trust.
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

      {/* Pictures, not working controls (apart from the step buttons): the sections below tell the same story in words. */}
      <div className="hero-visual" ref={visualRef}>
        <Shield pulse={stage} tracking={tracking} />
        <Story onStage={setStage} />
      </div>

      <ul className="hero-glance" aria-label="What SafePay Guardian does for each person">
        <li>
          <span className="glance-icon" aria-hidden="true">
            <PersonIcon />
          </span>
          <div>
            <h2>For the sender</h2>
            <p>Pay as usual. Risky payments wait, with the reasons in plain words.</p>
          </div>
        </li>
        <li>
          <span className="glance-icon" aria-hidden="true">
            <GuardianIcon />
          </span>
          <div>
            <h2>For the guardian</h2>
            <p>See only what matters, with the worrying words highlighted.</p>
          </div>
        </li>
        <li>
          <span className="glance-icon" aria-hidden="true">
            <ShieldUpIcon />
          </span>
          <div>
            <h2>Safe by design</h2>
            <p>Money is held, not sent. No answer means cancelled.</p>
          </div>
        </li>
      </ul>
    </section>
  )
}

function HowToUse() {
  const [who, setWho] = useState<Who>('sender')
  return (
    <Section id="how-to-use" eyebrow="How to use it" title="Two people, one simple routine"
      intro="Pick a side.">
      <div className="role-tabs" role="tablist" aria-label="Show the steps for">
        {(['sender', 'guardian'] as const).map((w) => (
          <button key={w} type="button" role="tab" id={`tab-${w}`} aria-selected={who === w}
            aria-controls="steps-panel" onClick={() => setWho(w)}>
            {w === 'sender' ? 'If you send money' : 'If you are the guardian'}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="steps-panel" aria-labelledby={`tab-${who}`}>
        <ol className="steps stagger" key={who}>
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
            <strong>The money waits.</strong> PayPal reserves it, but does not take it.
          </li>
          <li>
            <strong>Two checks.</strong> Safety rules and an AI (Gemini) read the message.
          </li>
          <li>
            <strong>One level.</strong> Low sends. Medium asks you to double-check. High waits for your guardian.
          </li>
          <li>
            <strong>A person decides.</strong> Approve sends it. Anything else cancels it.
          </li>
        </ul>

        <ol className="flow stagger" aria-label="The path of a payment">
          <li>
            <span className="flow-dot" aria-hidden="true" />
            You press Send for check
          </li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            PayPal reserves the amount
          </li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            Safety rules check it
          </li>
          <li className="flow-and">AND</li>
          <li>
            <span className="flow-dot" aria-hidden="true" />
            The AI reads the message
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
            Approve: sent. Otherwise: released.
          </li>
        </ol>
      </div>
    </Section>
  )
}

function CountStat({ to }: { to: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const n = useCountUp(to, ref)
  return (
    <div className="trust-stat" ref={ref}>
      <span className="sr-only">
        {to} of {to}
      </span>
      <span aria-hidden="true">
        {n} of {to}
      </span>
    </div>
  )
}

const TRUST = [
  { icon: <LockIcon />, title: 'Nothing is sent early', text: 'Money is reserved until someone says go.' },
  { icon: <ClockIcon />, title: 'Silence is safe', text: 'No answer cancels the payment.' },
  { icon: <QuoteIcon />, title: 'Every reason is quoted', text: 'Each reason quotes the message word for word.' },
  { icon: <ShieldUpIcon />, title: 'AI can only add caution', text: 'It can raise a risk level, never lower it.' },
  { icon: <ListIcon />, title: 'Everything is on record', text: 'Every decision is in an audit log.' },
]

function WhyTrust() {
  return (
    <Section id="why-trust" eyebrow="Why trust it" title="Built to fail safe" center
      intro="Built so a doubtful payment waits instead of going.">
      <div className="trust stagger">
        <div className="trust-card">
          <span className="icon-badge" aria-hidden="true">
            <ChartIcon />
          </span>
          <CountStat to={46} />
          <h3>Scams flagged in testing</h3>
          <p>On 69 unseen test cases: 44 held, none of 17 everyday payments held.</p>
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

      <Section id="who" eyebrow="Who it is for" title="For people who send money, and who look out for them"
        intro="Scammers push people to pay fast. We add a calm pause and a trusted second opinion.">
        <div className="audience stagger">
          <div className="audience-card">
            <span className="icon-badge" aria-hidden="true">
              <PersonIcon />
            </span>
            <h3>The sender</h3>
            <p className="muted">Anyone pushed to pay by a call or text.</p>
            <ul>
              <li>Pays as usual</li>
              <li>Sees why a payment looks risky</li>
              <li>Never argues with a scammer</li>
            </ul>
          </div>
          <div className="audience-card">
            <span className="icon-badge" aria-hidden="true">
              <GuardianIcon />
            </span>
            <h3>The guardian</h3>
            <p className="muted">A family member, friend or carer.</p>
            <ul>
              <li>Hears only about risky payments</li>
              <li>Sees the evidence</li>
              <li>Talks it through, then decides</li>
            </ul>
          </div>
        </div>
      </Section>

      <HowToUse />
      <HowItWorks />
      <WhyTrust />

      <Section id="faq" eyebrow="Questions" title="Common questions" center>
        <div className="faq stagger">
          {FAQS.map((f) => (
            <details key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </div>
      </Section>

      <section className="cta-band" aria-labelledby="cta-title">
        <span className="drift d1" aria-hidden="true" />
        <span className="drift d2" aria-hidden="true" />
        <span className="drift d3" aria-hidden="true" />
        <h2 id="cta-title">See it for yourself</h2>
        <p>Send a scam message as the sender, then decide as the guardian.</p>
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
