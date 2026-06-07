# 移动端响应式规范

> **本节讲解 GetRich 前端的移动端响应式设计与静态审计**。所有页面必须在手机（≥ 360px）、平板（≥ 768px）、桌面（≥ 1024px）三档下都可用。`scripts/audit_responsive.py` 是廉价的静态扫描器，5 条规则 + 1 个移动端导航检查，能在 30 秒内抓出 90% 的常见断点。
>
> 源码：`scripts/audit_responsive.py`（Round #1164）+ 测试 `tests/scripts/test_audit_responsive.py`

---

## 1. 设计目标

| 设备 | 视口 | 用户场景 | 验收 |
|---|---|---|---|
| 手机 | 360 × 640（iPhone SE） | 通勤路上看信号、查持仓 | 横向无滚动、按钮可点（≥ 32×32） |
| 平板 | 768 × 1024 | 办公桌看回测、订阅 | 多列布局、字体不挤 |
| 桌面 | 1280+ | 主力使用 | 全功能、含 3-4 列 dashboard |

**核心约束**：

1. **不依赖横向滚动**（除表格内）
2. **触摸目标 ≥ 32×32 px**（Apple HIG / Material Design 推荐）
3. **核心功能（看信号 / 看回测）手机可达**

---

## 2. 5 + 1 条审计规则

### 2.1 `fixed-width-overflows-mobile`

> 静态匹配：`w-[NNNpx]` 且 N > 343

**问题示例**：

```tsx
<div className="w-[800px]">wide</div>
// → 360px 屏幕上 800px div 必然横向滚动
```

**修法**：

```tsx
<div className="w-full sm:w-[800px]">wide</div>
// 或
<div className="max-w-full">bounded</div>
```

> **iPhone SE 375px - 32px gutter = 343px** 是上限。

### 2.2 `grid-cols-N-without-mobile-fallback`

> 静态匹配：`grid-cols-{3,4,5,6}` 但同 line 没有更小的 `grid-cols-{1,2}` 链

**问题示例**：

```tsx
<div className="grid grid-cols-4 gap-2">cards</div>
// → 360px / 4 = 90px/列，每张卡塞不下
```

**修法**：

```tsx
<div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2">cards</div>
```

**允许例外**：`grid-cols-1` / `grid-cols-2`（手机 2 列可接受）。

### 2.3 `overflow-x-auto-review`

> 静态匹配：`overflow-x-auto` 出现在非 table 元素上

**问题示例**：

```tsx
<div className="flex overflow-x-auto">
  <Card className="min-w-[400px]" />  {/* 横向滚动条 */}
</div>
```

**修法**：

```tsx
// 1. 加 min-w-0 让 flex 子元素真的能缩
<div className="flex overflow-x-auto min-w-0">

// 2. 改用 max-w-full 而非 min-w
<div className="overflow-x-auto max-w-full">
```

**允许例外**：

- shadcn/ui `<Table>` 组件（父 div 必带 `overflow-x-auto`）
- `<table>` 紧跟 `overflow-x-auto` 的行（前 5 行内）

### 2.4 `touch-target-too-small`

> 静态匹配：`<button>` 行上有 `h-6` / `w-6` / `h-5` / `w-5`，且**没有** `p-N` 补偿

**问题示例**：

```tsx
<button className="h-6 w-6">×</button>
// → 24×24 px，手指点不准
```

**修法**：

```tsx
// 1. 用 shadcn Button size="icon"（h-10 w-10）
<Button size="icon" variant="ghost"><X /></Button>

// 2. 或加 p-2 撑大点击区
<button className="h-6 w-6 p-2"><X /></Button>
```

> **iOS HIG**: ≥ 44pt / **Material Design**: ≥ 48dp / **本项目阈值**: ≥ 32px（折中）。

### 2.5 `desktop-only-nav`

> 静态匹配：`hidden md:flex` 在 Layout/App.tsx 中，且同 file 5 行内**没有** `md:hidden` 兄弟

**问题示例**：

```tsx
// Layout.tsx
<nav className="hidden md:flex">
  <NavItem>...</NavItem>
</nav>
// → 手机用户看到空 nav 栏
```

**修法**：

```tsx
<header>
  <Button className="md:hidden" onClick={openDrawer}>
    <Menu />
  </Button>
  <nav className="hidden md:flex">
    <NavItem>...</NavItem>
  </nav>
  <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
    <SheetContent side="left">
      <NavItem>...</NavItem>
    </SheetContent>
  </Sheet>
</header>
```

### 2.6 `overflow-x-auto-review`（已被 Table 例外白名单）

> 第 3 条规则的扩展，shadcn/ui `<Table>` 自动豁免。

---

## 3. 运行审计

### 3.1 本地 review（默认 report-only）

```bash
python scripts/audit_responsive.py
# 期望：报告 0 issues
# [audit_responsive] OK — 31 files scanned, 0 issues
```

### 3.2 阻塞模式（CI 等价）

```bash
python scripts/audit_responsive.py --strict
# 任何 issue → exit 1
```

### 3.3 JSON 输出

```bash
python scripts/audit_responsive.py --json | jq '.[] | {rule, file, line}'
```

### 3.4 排除 test 文件

`audit_file()` 默认跳过 `.test.tsx`（test 不上线，不修）。可加 `--include-tests` 强制审计。

---

## 4. 修复模式速查

### 4.1 卡片网格

```tsx
// ❌ 4-col 无 fallback
<div className="grid grid-cols-4 gap-4">

// ✅ 1 → 2 → 4 渐进
<div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
```

### 4.2 表格

```tsx
// ❌ table 直接露出
<table>...</table>

// ✅ 包裹滚动 div
<div className="overflow-x-auto max-w-full">
  <table className="w-full">...</table>
</div>
// (shadcn/ui Table 自带此结构)
```

### 4.3 长文本

```tsx
// ❌ 硬宽度
<p className="w-[600px]">{description}</p>

// ✅ 自适应
<p className="max-w-prose">{description}</p>
```

### 4.4 导航

```tsx
// ❌ 桌面 only
<nav className="hidden md:flex">...</nav>

// ✅ 双端
<>
  <Button className="md:hidden" onClick={openDrawer}><Menu /></Button>
  <nav className="hidden md:flex">...</nav>
  <Sheet open={open} onOpenChange={setOpen}>...</Sheet>
</>
```

### 4.5 图表

```tsx
// ❌ 固定高度
<div className="h-[600px]"><ECharts /></div>

// ✅ 视口相关
<div className="h-[300px] sm:h-[400px] md:h-[600px]"><ECharts /></div>
```

---

## 5. Tailwind 移动端约定

### 5.1 Breakpoint

| 前缀 | 视口 | 用途 |
|---|---|---|
| （无） | < 640 | 手机：1 列 / 栈式 |
| `sm:` | ≥ 640 | 大手机 / 小平板：2 列 |
| `md:` | ≥ 768 | 平板：2-3 列 |
| `lg:` | ≥ 1024 | 桌面：3-4 列 + 侧栏 |
| `xl:` | ≥ 1280 | 宽屏：更宽容器 |

> **本项目约定**：手机先写无前缀 → `sm:` → `md:` → `lg:`，**反方向不写**（避免维护困难）。

### 5.2 容器宽度

```tsx
<div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
  {/* 内容 */}
</div>
```

### 5.3 字体

```tsx
<h1 className="text-2xl sm:text-3xl md:text-4xl">Title</h1>
<p className="text-sm sm:text-base">Body</p>
```

### 5.4 间距

```tsx
<section className="py-8 sm:py-12 md:py-16">
  <div className="space-y-4 sm:space-y-6">
    <Card className="p-4 sm:p-6">...</Card>
  </div>
</section>
```

### 5.5 ECharts 响应式

```tsx
const option = {
  grid: { left: 40, right: 16, top: 32, bottom: 32, containLabel: true },
  // containLabel: true 让 y 轴 label 算进 grid，移动端不裁切
}

// ECharts 实例需要响应窗口 resize
useEffect(() => {
  const handler = () => chartRef.current?.resize();
  window.addEventListener("resize", handler);
  return () => window.removeEventListener("resize", handler);
}, []);
```

---

## 6. 触摸目标 & 可访问性

### 6.1 触摸目标尺寸

| 元素类型 | 最小尺寸 | 推荐 |
|---|---|---|
| 主按钮 | 32×32 | 40-48px |
| Icon 按钮 | 32×32 | 40×40（`size="icon"`） |
| 链接（密集列表） | 24×24 行高 | 32px 行高 |
| 表单 input | 32px 高 | 40px |

### 6.2 间距

- 可点击元素**之间**至少 8px 间距
- 文本行高 ≥ 1.5（WCAG AA）

### 6.3 焦点指示

```tsx
// 强制保留 focus ring
<button className="focus-visible:ring-2 focus-visible:ring-offset-2">
  Click
</button>
```

> 默认 Tailwind `outline-none` 在用 `focus-visible:ring-*` 替代后，键盘用户仍能看到焦点。

---

## 7. 测试

### 7.1 单元测试（6 个）

`tests/scripts/test_audit_responsive.py` 覆盖：

| 测试 | 验证 |
|---|---|
| `test_audit_finds_known_bad_patterns` | 3 个 known-bad 都被 flag |
| `test_audit_skips_known_good_patterns` | 3 个 known-good 不 flag |
| `test_audit_strict_exits_nonzero_on_issues` | `--strict` → exit 1 |
| `test_audit_default_exits_zero` | 默认 report-only → exit 0 |
| `test_audit_human_output_includes_fix_suggestion` | 人读输出有 `fix:` 行 |
| `test_audit_groups_by_file` | 按文件分组，方便 review |

### 7.2 视觉回归（Playwright，可选）

```bash
# 仅本地跑
npx playwright test --project=mobile
# 截图：tests/screenshots/mobile/*.png
```

### 7.3 手动 checklist

每次 PR 检查：

- [ ] iPhone SE 视口（375×667）打开主路径
- [ ] iPad 视口（768×1024）打开主路径
- [ ] 横向旋转 phone → landscape 不破

---

## 8. CI 集成

### 8.1 pre-commit hook

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: audit-responsive
      name: Mobile responsive audit
      entry: python scripts/audit_responsive.py --strict
      language: system
      types: [tsx]
      pass_filenames: false
```

> 跑全量（不传 file）确保不漏。预提交时 1-2 秒搞定。

### 8.2 docs CI（最严）

```yaml
# .github/workflows/docs.yml 末尾追加
- name: Mobile responsive audit
  run: python scripts/audit_responsive.py --strict
```

> 任何 issue 直接 fail PR。

---

## 9. 已知误报与白名单

### 9.1 shadcn/ui Table 组件

`frontend/src/components/ui/table.tsx` 的 `<Table>` 组件父 div 必带 `overflow-x-auto`，**已自动豁免**（脚本看 `<table` 在同 line 或 5 行内 → 跳过）。

### 9.2 极小 icon 按钮

某些 UI 设计确实用 24×24 icon（settings / close × 按钮）。**审计会报**，需要：

1. 加 `p-2` 撑大（首选）
2. 加 `// audit-ok: design-decision` 注释到该行（人工豁免，下版本脚本支持注释豁免）

> ⚠️ 注释豁免**待实现**；当前用 1）解决。

### 9.3 桌面专属页

如有页面**仅桌面可用**（如大型回测报告），应在路由层加 `<MediaQuery mobileOnly>` 提示，避免被审计抓到。**目前无此类页面**。

---

## 10. 进一步阅读

- 工具链：[Tailwind CSS 4 响应式](https://tailwindcss.com/docs/responsive-design)
- 设计参考：
    - [Apple Human Interface Guidelines — Touch targets](https://developer.apple.com/design/human-interface-guidelines/inputs/touch-targets/)
    - [Material Design — Touch targets](https://m3.material.io/foundations/accessible-design/accessibility-basics)
- 工具：
    - [Tailwind breakpoint debugger](https://tailwindcss.com/docs/breakpoints)
    - [Chrome DevTools — Device toolbar](https://developer.chrome.com/docs/devtools/device-mode/)
- 源码：
    - [`scripts/audit_responsive.py`](https://github.com/getrich/getrich/blob/main/scripts/audit_responsive.py)
    - [`tests/scripts/test_audit_responsive.py`](https://github.com/getrich/getrich/blob/main/tests/scripts/test_audit_responsive.py)
