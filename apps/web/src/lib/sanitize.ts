import DOMPurify from 'dompurify'

/**
 * 清洗作者提供的富文本 HTML（如 `strategy.detail_html`），再交给 `dangerouslySetInnerHTML`。
 *
 * 只保留排版所需的 HTML 配置：去掉脚本、事件属性、`javascript:` 链接与 SVG/MathML。
 * 后端的长度限制与 bleach 归一化是另一道防线，前端不能因此省略清洗（AGENTS.md §5）。
 */
export function sanitizeHtml(html: string | null | undefined): string {
  if (!html) return ''
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style'],
  })
}
