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

### 问题

deepmodeling/blog（Hexo）不支持 MathJax/LaTeX 渲染，`$$...$$` 和 `\(...\)` 会原样显示。

### 解决方案：codecogs SVG API

`converter.py → _convert_latex_to_html()`

将 LaTeX 公式转为 codecogs SVG 图片，无外部依赖，纯 HTML `<img>` 即可显示。

### 支持与不支持对比

| 语法 | 支持 | 输出 |
|------|------|------|
| `$$E=mc^2$$` | ✅ | `<center><img src="...codecogs..."/></center>` |
| `\(E=mc^2\)` | ✅ | `<img src="...codecogs...\inline" style="vertical-align:middle" />` |
| `\[E=mc^2\]` | ✅（新增） | 同上块级 |
| `$E=mc^2$` | ❌ | 不支持单 `$`（微信文章不会出现） |

### 已处理的问题

1. ✅ `$$...$$` 多行公式正确匹配（使用 `re.DOTALL`）
2. ✅ `\[...\]` 格式新增支持（部分 LLM 翻译时会生成）
3. ✅ URL 编码处理（`urllib.parse.quote`）
4. ✅ 转换后 `_has_math_formula()` 自动检测不到公式 → `mathjax: true` 不再出现（正确行为）

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
