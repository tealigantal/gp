// 轻量别名映射：常见指数与板块关键词到代码
const ALIAS: Record<string, string> = {
  '上证指数': '000001.SH',
  '沪指': '000001.SH',
  '深证成指': '399001.SZ',
  '深成指': '399001.SZ',
  '创业板指': '399006.SZ',
  '沪深300': '000300.SH',
  '中证1000': '000852.SH',
  '上证50': '000016.SH',
  '科创50': '000688.SH'
}

export function resolveSymbolsFromText(text: string): string[] {
  const t = text.trim()
  const codes = new Set<string>()
  const m = t.match(/\b\d{6}\b/g)
  for (const c of m || []) codes.add(c)
  for (const [k, v] of Object.entries(ALIAS)) {
    if (t.includes(k)) codes.add(v)
  }
  return Array.from(codes)
}

