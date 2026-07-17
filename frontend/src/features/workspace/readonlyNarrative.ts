import type { CanonicalMessage } from '../../shared/contracts'

export function isReadonlyCanonicalMessage(message: CanonicalMessage | undefined): boolean {
  void message
  return false
}

export function buildReadonlyNarrative(message: CanonicalMessage | undefined): string | null {
  void message
  return null
}
