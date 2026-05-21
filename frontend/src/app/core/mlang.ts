export function parseMlang(text: string | null | undefined, lang: string): string {
  if (!text) return '';
  const mlangRegex = /\{mlang\s+([a-z_-]+)\}([\s\S]*?)\{mlang\}/gi;
  const blocks: Record<string, string> = {};
  let hasMlang = false;
  let match: RegExpExecArray | null;
  while ((match = mlangRegex.exec(text)) !== null) {
    hasMlang = true;
    const key = match[1].toLowerCase();
    blocks[key] = (blocks[key] || '') + match[2];
  }
  if (!hasMlang) return text;

  const fallbacks = [lang.toLowerCase(), 'en', 'other'];
  for (const candidate of fallbacks) {
    if (blocks[candidate]) return blocks[candidate].trim();
  }
  const first = Object.values(blocks)[0];
  return first ? first.trim() : '';
}
