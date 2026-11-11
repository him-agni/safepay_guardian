/*
 * The three demo scenarios, ready to load into the send form with one click (shown in demo mode only).
 *
 * The stored AI replies only match when the payee, amount, note and message are exactly the demo's, so typing them
 * by hand almost always misses. This is a copy of demo/scenarios.json; a test keeps the two in step.
 * Scenario 3 is a screenshot: the picture is served from public/demo/ (the same bytes as demo/screenshots/, because
 * the stored transcription is looked up by the image's fingerprint).
 */

export interface DemoScenario {
  id: string
  label: string
  hint: string
  payee_name: string
  amount: string
  note: string
  message_text: string
  screenshot?: string // address of the picture, for scenario 3
}

export const DEMO_SCREENSHOT_URL = '/demo/bank-fraud-team-text.png'

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: '1-obvious-scam',
    label: '1. Gift-card scam',
    hint: 'A fake government agent demands $500 in gift cards. Held for the guardian.',
    payee_name: 'Officer Collins',
    amount: '500.00',
    note: '',
    message_text:
      'This is Officer Collins with the IRS. You owe $500 in back taxes. You must pay in gift cards within 30 minutes or a warrant will be issued for your arrest.',
  },
  {
    id: '2-legit-contractor',
    label: '2. Legitimate contractor',
    hint: 'A $350 deposit to a new contractor. Unusual but real: a warning, not a block.',
    payee_name: 'Gutter Pros',
    amount: '350.00',
    note: 'deposit for gutter repair',
    message_text:
      'Hi Margaret, this is Mike from Gutter Pros. As we discussed on Saturday, here is the invoice for the deposit on the gutter repair (invoice #1042 attached). We can start next Tuesday. Thanks!',
  },
  {
    id: '3-polite-bank',
    label: "3. Polite 'bank' text",
    hint: 'A screenshot of a polite text asking to move $300 to a "protected account". Only the AI catches it.',
    payee_name: 'Secure Holdings LLC',
    amount: '300.00',
    note: '',
    // used only if the screenshot cannot be read; normally the text comes from reading the picture
    message_text:
      "Good afternoon, this is Daniel from the Fraud Prevention Team at your bank. We noticed unusual sign-in activity on your account. As a precaution, please move $300 to the protected account our security team has set up in your name: Secure Holdings LLC. We will return it once the review is complete. Thank you for your cooperation.",
    screenshot: DEMO_SCREENSHOT_URL,
  },
]

/** Demo buttons show when the backend replays stored AI answers, or when the address has ?demo (for recording). */
export function isDemoMode(health: { ai?: { provider?: string } } | null, search: string): boolean {
  if (new URLSearchParams(search).has('demo')) return true
  return health?.ai?.provider === 'replay'
}
