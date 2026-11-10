// Short, calm advice for the sender while a payment waits for the guardian. Written in our own words from
// public consumer guidance (FTC, FBI IC3, AARP). No brand names, so it can appear in the demo video.

const GENERAL = [
  'Nobody real will ask you to pay with gift cards, crypto or a wire transfer.',
  'It is OK to hang up and call back on a number you look up yourself, not one from the message.',
  'Real organizations do not rush you or ask you to keep a payment secret.',
]

const BY_CATEGORY: Record<string, string> = {
  government_impersonation:
    'Government agencies do not demand payment by phone or text, and never threaten arrest to get paid.',
  bank_impersonation: 'Your bank will never ask you to move money to a "safe" or "protected" account.',
  tech_support: 'Real tech companies do not contact you out of the blue asking to be paid to fix your computer.',
  grandparent: 'If a family member asks for money in an emergency, call them back on the number you already have.',
  family_impersonation: 'If someone says they are family on a new number, call the number you already have for them.',
  romance: 'Never send money to someone you have only met online, however kind they seem.',
  prize: 'You never have to pay a fee to receive a prize or a refund.',
  contractor: 'Check a contractor\'s name and reviews before paying, and avoid paying everything up front.',
  utility_impersonation: 'Utility companies do not threaten to cut you off today unless you pay right now.',
  delivery: 'Delivery companies do not ask for payment by text to release a parcel.',
  employment: 'A real job never asks you to pay to start, or to send money back to them.',
  investment: 'Promises of guaranteed or very fast returns are a warning sign.',
  charity: 'Give to a charity through its own website, not through a message that pressures you.',
  rental: 'Do not pay a deposit for a home you have not seen, to someone you cannot meet.',
}

/** Three tips: the one for this kind of scam first (if we know it), then the general ones. */
export function safetyTips(category: string | null | undefined): string[] {
  const specific = category ? BY_CATEGORY[category] : undefined
  return specific ? [specific, ...GENERAL.slice(0, 2)] : GENERAL
}
