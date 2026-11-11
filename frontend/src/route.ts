/** Split a URL hash like "#/guardian/p/abc" into its parts. A part that is not valid percent-encoding is kept as is. */
export function parseHash(hash: string): string[] {
  return hash
    .replace(/^#\/?/, '')
    .split('/')
    .filter(Boolean)
    .map((part) => {
      try {
        return decodeURIComponent(part)
      } catch {
        return part // "%E0%A4%A" and the like would throw and blank the whole page
      }
    })
}
