# 公式处理记录

本文件记录微信公众号文章公式处理过程中遇到的各类问题及解决方案。

---

## 一、公式来源与格式

微信公众号文章使用 MathJax 渲染数学公式，但不同作者、不同编辑器导出的 HTML 格式差异很大。

### 已知的公式 HTML 格式

| 格式 | HTML 标签 | 提取难度 | 状态 |
|------|----------|---------|------|
| MathJax script 块级 | `<script type="math/tex; mode=display">` | ✅ 容易 | 已支持 |
| MathJax script 行内 | `<script type="math/tex">` | ✅ 容易 | 已支持 |
| MathJax span 块级 | `<span class="mjx-container">` | ⚠️ 需提取嵌套文本 | 已支持 |
| MathJax span 行内 | `<span class="mjx-inline">` | ⚠️ 需提取嵌套文本 | 已支持 |
| data-math 属性 | `<span data-math="E=mc^2">` | ✅ 容易 | 已支持 |
| **mjx-container 自定义元素** | `<mjx-container data-formula="...">` | ✅ 容易 | 已支持（2026-10 修复） |
| **CSS 模拟下标** | `<span style="vertical-align:sub; font-size:smaller">` | ❌ 不是 LaTeX | **无法提取** |

### 最后一种格式的问题

部分微信文章的简单行内公式（如 T_c、p_c）不使用 MathJax，而是直接用 CSS 样式模拟：
```html
T<span style="vertical-align:sub;font-size:smaller">c</span>
```
markdownify 转换时丢弃 CSS 样式，导致公式变成空白。下载器无法识别这种格式，因为它不包含任何 LaTeX 源码。

---

## 二、下载器公式提取历程

### 初版（只处理 script 和 span.mjx-）

`downloader.py → _extract_formula()`

- 匹配 `<script type="math/tex">` 和 `<span class="mjx-*">`
- 问题：只检查元素自身，公式嵌套在 `<p>` 内部时被漏掉

### 改进 1：增加 data-math 和嵌套 script 提取

- 新增 `data-math` / `data-latex` 属性检查
- 新增 MathJax span 内嵌套 `<script>` 的递归查找
- 新增调试日志 `🔍 [公式调试]` 打印未识别的公式元素

### 改进 2：嵌套公式占位符保护

`downloader.py → _convert_element()`

- 问题：公式嵌套在 `<p>` / `<section>` 内部时，markdownify 丢弃 MathJax HTML
- 修复：在 markdownify 之前扫描所有子元素中的公式，替换为占位符，转换后恢复
- 新增 `_has_nested_formulas()` 和 `_replace_nested_formulas()`

### 仍未解决的问题

CSS 模拟下标（`vertical-align:sub`）不含 LaTeX 源码，下载器无法提取。这类文章依赖 LLM 翻译时从上下文推断公式内容（不可靠，取决于 LLM 的"脑补"能力）。

---

## 三、翻译阶段公式处理

### 翻译 prompt 要求

`translator.py` 要求 LLM：
- 保留 `$$...$$` 和 `\(...\)` 不变
- 保留图片链接不变

### LLM 非确定性行为

| 现象 | 说明 |
|------|------|
| LLM 推断缺失公式 | 当 zh.md 中公式为空白时，LLM 有时能从上下文推断出正确公式（如补回 `\(T_c\)`） |
| LLM 不推断 | 同样的文章同样的 prompt，LLM 可能不推断，输出空白 |
| LLM 生成 `\[...\]` | 翻译时可能将块级公式写成 `\[...\]` 而非 `$$...$$` |

**结论**：LLM 推断不可靠，但大多数有公式的学术文章 LLM 都能正确推断。

---

## 四、格式转换阶段公式处理

### 现状（2026-10 改）

`converter.py → _normalize_latex()` 将 `\(...\)`、`\[...\]` 归一化为
`$...$`、`$$...$$`，交由站点已全局加载的 MathJax 3.2.2 渲染。

`_has_math_formula()` 在归一化前执行，检测到任意公式分隔符后向
frontmatter 写入 `mathjax: true`，触发 NexT 主题的逐页 `enableMath` 开关。

### 分隔符对照

| 输入 | 输出 | 说明 |
|------|------|------|
| `\(...\)` | `$...$` | 下载器从 `data-formula` 提取的原始形态 |
| `\[...\]` | `$$...$$` | LLM 翻译有时生成 |
| `$$...$$` | 原样保留 | 已是 MathJax 认识的块级形式 |
| `$...$` | 原样保留 | 已是 MathJax 认识的行内形式 |

### 为什么不再用 codecogs

旧方案把公式转成 `<img src="https://latex.codecogs.com/...">` 外链图片。
这条路径有三个问题：

1. **深色模式不可见**：codecogs SVG 的 `fill="currentColor"` 在 `<img>` 独立
   文档上下文里无法继承父页 CSS，回退为黑色；站点 `darkmode: true`，
   主题 CSS 未对 `img` 做反色补偿，公式在深色背景上看不见。
2. **时序 bug**：旧 `_has_math_formula()` 在 `_convert_latex_to_html()`
   之后执行，此时公式已变成 `<img>` 标签，检测恒 False，`mathjax: true`
   永远不加（虽然加了也没有意义，因为走的是图片路径）。
3. **外部依赖**：仓库 104 篇已发布文章里 codecogs 用例为 0，`$...$` +
   MathJax 用例 19 篇。

### 已处理的问题

1. ✅ `_has_math_formula` 扩展为支持四种分隔符（`\(...\)` `\[...\]` `$$` `$`）
2. ✅ `has_math` 在归一化前计算，传给 `_build_frontmatter(has_math=...)`
3. ✅ codecogs URL 全部移除，`_convert_latex_to_html` 更名为 `_normalize_latex`
4. ✅ 回归测试：无公式的文章不加 `mathjax: true`

---

## 五、测试验证

使用文章《ABACUS还能干这个？铝的气液临界点研究》（大量行内公式）反复测试：

| 运行 | zh.md 公式 | LLM 推断 | en.md 公式 | blog 公式转换 | 结果 |
|------|-----------|---------|-----------|-------------|------|
| 162924 | ❌ 空白 | ✅ 推断成功 | `\(T_c\)`, `\[...\]` | `\(...\)` ✅, `\[...\]` ❌ | 部分成功 |
| 164106 | ❌ 空白 | ❌ 未推断 | 空白 | 空白 | 失败 |
| 165017 | ❌ 空白 | ❌ 未推断 | 空白 | 空白 | 失败 |
| 165627 | ❌ 空白 | ✅ 推断成功 | `\(T_c\)`, `\[...\]` | 全部 ✅ | ✅ 成功 |

**最终结论**：公式转换模块已完备。下载器提取问题仅影响 zh.md 保真度，不影响最终博客输出（LLM 翻译时可弥补）。CSS 模拟下标格式的提取作为后续优化项。

---

*最后更新: 2026-07-15*
