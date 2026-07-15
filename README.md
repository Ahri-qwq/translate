# 微信公众号文章 → 博客格式 全自动流水线

一站式工具：下载微信文章 → LLM 翻译 → 审核 → OSS 上传图片 → 格式转换 → 输出 deepmodeling/blog 兼容的 Markdown。

## 🎯 功能

- 下载微信公众号文章（内容 + 图片）
- **智能图片重编号**：按正文出现顺序统一重编号为 pic1/pic2/...
- 多 LLM 翻译（支持 Qwen / DeepSeek，可随时切换对比）
- **LLM 自动审核**翻译质量（支持双模型交叉审查）
- **OSS 图片上传**：自动上传到阿里云 OSS 并替换为 HTTPS 地址
- **LaTeX 公式转换**：自动将 `$$...$$` / `\(...\)` / `\[...\]` 转换为 codecogs SVG 图片
- 自动转换为博客格式（frontmatter + `<center><img>` + `<!-- more -->`）
- LLM 自动分类（categories）
- 全自动流水线：一条命令完成下载→翻译→审核→上传→转换→分类→GitHub PR
- **GitHub PR 自动提交**：通过 gh CLI 自动创建 PR 到目标仓库（branch → push → PR，不动 master）
- **项目与目标仓库隔离**：目标仓库缓存在项目外部，互不污染
- **容错设计**：任意步骤出错时提示重试/跳过，不阻塞流水线

## 📁 项目结构

```
translate/
├── config.yaml              # LLM + OSS + 审查 + GitHub 多合一配置（不入库）
├── config.yaml.example      # 配置文件模板（可入库，供新用户参考）
├── .gitignore               # 排除敏感配置和输出文件
├── requirements.txt         # Python 依赖
├── src/
│   ├── main.py              # 主入口（交互 / 命令行 / 批量）
│   ├── downloader.py        # 下载 + 图片重编号
│   ├── translator.py        # LLM 翻译 + 审核 + 交叉审查
│   ├── converter.py         # 格式转换 + 公式转换 + LLM 分类
│   ├── oss_uploader.py      # 阿里云 OSS 图片上传
│   └── github_uploader.py   # GitHub PR 自动提交
├── data/
│   ├── OSS/oss工具.md         # 阿里云 OSS 工具文档索引
│   ├── Todo.md                 # 任务列表
│   ├── formula-handling.md     # 公式处理问题记录
│   └── blog/source/_posts/     # 参考博客源文件（用于格式对齐）
└── output/                  # 输出目录
    └── article_{时间戳}/
        ├── {标题}_zh.md           # 中文原文（含元数据块）
        ├── {标题}_en.md           # 英文翻译（含翻译元数据）
        ├── {标题}_review.md       # 审核报告（有问题时生成）
        ├── {标题}.images_map.txt  # 图片 URL 映射（上传后更新为 OSS 地址）
        ├── images/                # 下载的图片（pic1.png, pic2.png, ...）
        └── blog_output/
            └── {CATEGORY}_{YYYY}_{MM}_{DD}.md  # 最终博客文件
```

## 🚀 使用方法

### 交互模式（推荐）

```bash
python src/main.py
```

然后按提示选择 LLM 和模型，输入文章链接即可全自动完成。

```
可用 LLM 提供商:
  [1] qwen         当前默认: qwen3.7-max
  [2] deepseek     当前默认: deepseek-v4-pro
  [Enter] 退出

选择 LLM: 2

deepseek 可用模型:
  [1] deepseek-v4-pro ★默认
  [2] deepseek-v4-flash
  [3] deepseek-v4.1
  [4] deepseek-chat
  [5] deepseek-reasoner
  [Enter] 使用默认

模型: 2

微信文章链接 [回车退出]: https://mp.weixin.qq.com/s/xxx
```

### 命令行模式

```bash
# 单篇全自动处理
python src/main.py --url "https://mp.weixin.qq.com/s/xxx"

# 指定 LLM 和模型
python src/main.py --url "..." --llm deepseek --model deepseek-v4-pro

# 仅下载（不翻译、不转换，但会上传 OSS 如果已配置）
python src/main.py --url "..." --download-only

# 批量处理（从文件读取 URL）
python src/main.py --file urls.txt --llm deepseek

# 单独运行格式转换
python src/converter.py --dir output/article_xxx --llm deepseek

# 单独运行 OSS 上传
python src/oss_uploader.py --dir output/article_xxx

# 单独运行 GitHub 上传
python src/github_uploader.py --dir output/article_xxx
python src/github_uploader.py --file output/article_xxx/blog_output/xxx.md
```

### 批量处理文件格式

创建 `urls.txt`：
```
https://mp.weixin.qq.com/s/xxx1
https://mp.weixin.qq.com/s/xxx2
https://mp.weixin.qq.com/s/xxx3
```

## 📦 安装依赖

### Python 依赖

```bash
pip install -r requirements.txt
```

依赖：
- `requests` — HTTP 请求
- `beautifulsoup4` — HTML 解析
- `markdownify` — HTML 转 Markdown
- `openai` — LLM API 调用（兼容 OpenAI / DeepSeek / DashScope）
- `pyyaml` — 配置文件解析

### 外部工具（可选）

- **ossutil 2.0** — 阿里云 OSS 命令行工具，用于图片上传。如不需要 OSS 上传功能可不安装。
  - 下载地址：https://help.aliyun.com/zh/oss/developer-reference/ossutil-overview/
- **GitHub CLI** (`gh`) — 用于自动创建 PR 上传博客。如不需要 GitHub 上传功能可不安装。
  ```bash
  winget install GitHub.cli    # Windows
  brew install gh              # macOS
  ```
  安装后登录：`gh auth login`

## ⚙️ 配置

**新用户第一步**：复制模板文件并填入实际值。

```bash
copy config.yaml.example config.yaml   # Windows
cp config.yaml.example config.yaml     # macOS / Linux
```

然后编辑 `config.yaml`，填入各服务的 API Key 和 AccessKey。

> `config.yaml` 已加入 `.gitignore`，不会被提交到 Git 仓库。

---

`config.yaml` 包含四部分：LLM 提供商、OSS 上传、翻译审查、GitHub 上传。

### LLM 提供商

```yaml
llm:
  default: "qwen"       # 默认提供商（可通过 --llm 参数覆盖）
  providers:
    qwen:
      api_key: "sk-xxx"
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      model_name: "qwen3.7-max"
    deepseek:
      api_key: "sk-xxx"
      base_url: "https://api.deepseek.com"
      model_name: "deepseek-v4-pro"
```

可用模型（运行时选择）：

| 提供商 | 模型 |
|--------|------|
| Qwen | `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-flash`, `qwen-max` |
| DeepSeek | `deepseek-v4-pro`, `deepseek-v4-flash`, `deepseek-v4.1`, `deepseek-chat`, `deepseek-reasoner` |

> **注意**：`deepseek-chat` 和 `deepseek-reasoner` 将于 2026/07/24 弃用，建议迁移至 `deepseek-v4-pro` / `deepseek-v4-flash`。

### OSS 图片上传

```yaml
oss:
  access_key_id: "LTAI5txxx"              # 阿里云 AccessKey ID（必填）
  access_key_secret: "xxx"                # 阿里云 AccessKey Secret（必填）
  bucket: "dp-public"                     # OSS Bucket 名称
  endpoint: "oss-cn-beijing.aliyuncs.com" # OSS Endpoint
  region: "cn-beijing"                    # Bucket 所在地域
  path_prefix: "community/Blog Files"     # OSS 上传路径前缀
```

> **提示**：如果未配置 OSS（AK 为空），流水线会自动跳过上传步骤，使用原始微信 CDN URL。

### 翻译审查

```yaml
review:
  cross_review: true          # 是否启用双模型交叉审查
  second_reviewer: "qwen"     # 第二个审查模型（引用 llm.providers 中的名称）
  max_revise_rounds: 1        # 最大修改轮次（审查未通过时自动修改）
```

**交叉审查流程**：当 `cross_review: true` 时，翻译完成后会由主模型 + 第二模型分别独立审查，合并两份报告（取较低分数、合并问题列表）。审查未通过时自动调用 LLM 修改译文。

### GitHub 博客上传

```yaml
github:
  repo: "deepmodeling/blog"         # 目标仓库
  branch: "master"                  # 目标分支（PR base）
  cache_dir: ""                     # 本地缓存目录（留空则默认 ../blog-cache）
```

**工作流程**：拉取最新 master → 创建 `post-{CATEGORY}_{YYYY}_{MM}_{DD}` 分支 → 复制博客文件 → 推送 → 创建 PR。绝不直接操作 master 分支。

**仓库隔离**：目标仓库 clone 到项目外部的缓存目录（默认 `../blog-cache`），与翻译项目仓库互不影响。

**前置条件**：需安装 GitHub CLI 并登录。
```bash
winget install GitHub.cli   # 安装
gh auth login               # 登录
```

> **提示**：如果未配置 GitHub 段或 gh 不可用，流水线会自动跳过上传步骤。

## 📝 处理流程

```
[Step 1/6] 下载文章
    ├── 提取正文、标题、公式
    ├── 智能图片重编号（按出现顺序 pic1/pic2/...）
    ├── 跳过音视频内容并标注
    └── 生成中文 Markdown + images_map.txt

[Step 2/6] LLM 翻译 + 审核
    ├── 中文 → 英文翻译（保留公式、图片、Markdown 语法）
    ├── LLM 审核（漏译 / 术语 / 格式）
    ├── 交叉审查（可选）：双模型独立审查，合并报告
    └── 未通过时自动修改译文（最多 N 轮，可配置）

[Step 3/6] 保存文件
    ├── {标题}_zh.md — 中文原文
    ├── {标题}_en.md — 英文译文（含翻译元数据头）
    ├── {标题}_review.md — 审核报告
    ├── {标题}.images_map.txt — 图片 URL 映射
    └── images/ — 下载的正文图片

[Step 4/6] OSS 上传（可选）
    ├── 上传 images/ 中所有图片到 OSS
    ├── 更新 images_map.txt 为 OSS HTTPS 地址
    └── 上传失败时自动回退到原始微信 CDN URL

[Step 5/6] 格式转换 → 博客格式
    ├── LLM 自动分类（categories）
    ├── 清理翻译元数据块（> Source, > Translated by 等）
    ├── LaTeX 公式 → codecogs SVG 图片
    ├── 图片语法转换（![](local) → <center><img src=url /></center>）
    ├── 图N → Figure N 自动翻译
    ├── 图片间加粗文本 → ## 二级标题
    ├── 自动插入 <!-- more -->（第一段落后）
    ├── 自动检测 mathjax: true
    └── 文件命名：{CATEGORY}_{YYYY}_{MM}_{DD}.md

[Step 6/6] 上传 GitHub → PR
    ├── 检查 gh CLI 可用 & 已登录
    ├── 同步本地缓存仓库（git pull origin master）
    ├── 创建分支 post-{CATEGORY}_{YYYY}_{MM}_{DD}
    ├── 复制 blog_output/*.md → source/_posts/
    ├── git commit + git push
    └── gh pr create → 返回 PR 链接
```

## 📊 输出格式

### 英文翻译文件（`_en.md`）

```markdown
# Translated English Title

> Source: https://mp.weixin.qq.com/s/xxx
> Original title: 中文原标题
> Translated by deepseek
> Quality score: 85/100 (PASSED)

---

Body content with images and formulas...
```

### 博客 Markdown（最终产物）

```markdown
---
title: "DP Can Also Do This? Deep Learning Potential Framework..."
date: 2026-07-14
categories:
- DeePMD-kit
---

<center><img src=https://oss-url/pic1.png pic_center width="100%" height="100%" /></center>

Body content...

<!-- more -->

## Section Title

More content...

<center><img src=https://oss-url/pic2.png pic_center width="100%" height="100%" /></center>
```

## 🧪 测试

```bash
# 测试翻译模块（使用内置示例文本，无需网络）
python src/translator.py

# 测试下载模块（需提供真实微信文章 URL）
python src/downloader.py

# 测试格式转换（需提供已有输出目录）
python src/converter.py --dir output/article_xxx

# 测试 OSS 上传（需提供已有输出目录）
python src/oss_uploader.py --dir output/article_xxx
```

## 📋 待完成

- [x] 上传 GitHub 脚本
- [ ] Markdown 表格格式自动修复（微信表格 → 标准 Markdown 表格）
- [ ] 公式提取增强：CSS 模拟下标格式（`vertical-align:sub`）的识别与 LaTeX 还原
- [ ] 公式提取增强：公式图片的 OCR/alt-text 识别

---

*Created: 2026-03-31 | Updated: 2026-07-15*
