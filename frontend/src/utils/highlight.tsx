import React from 'react'

export type Highlight = { start: number; length: number }

export function renderHighlight(text: string, highlights: Highlight[] = []) {
  if (!highlights || highlights.length === 0) return text
  const h = highlights[0]
  const start = Math.max(0, h.start)
  const end = Math.min(text.length, start + Math.max(0, h.length))
  const pre = text.slice(0, start)
  const mid = text.slice(start, end)
  const suf = text.slice(end)
  return (
    <span>
      {pre}
      <mark>{mid}</mark>
      {suf}
    </span>
  )
}

