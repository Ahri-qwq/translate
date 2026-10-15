# 领英动态自动化调研与规划

## 现状

当前工作流在 PR merge 后结束。领英发布完全手动。

## LinkedIn API 可行性调研（2026-10）

### 技术可行性

LinkedIn 提供 Posts API（`/rest/posts` 端点），可以向公司主页发帖。

**必须同时满足三个条件才能调用：**

1. App 必须获得 LinkedIn Marketing API 产品审批（需申请，不是自助开通）
2. OAuth token 必须携带 `w_organization_social` scope
3. 认证用户必须在目标公司主页持有 ADMIN 或 DSC 角色

**关键限制：**
- 产品审批流程不透明，时间不确定
- 申请时需要说明使用场景，个人/社区用途通过率低于商业产品
- 图片/链接预览卡片需要先上传媒体到 LinkedIn 再引用 URN
- 403 错误不说明是哪个条件不满足，调试困难

**参考链接：**
- [Posts API 文档](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api)
- [Organic Posts 用例](https://learn.microsoft.com/en-us/linkedin/marketing/usecases/page-management/organic-posts-usecase)
- [Organization Authorizations](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/organizations/organization-authorizations/getting-started)

### 结论

**短期不走 API 路线。** 审批门槛高，且 DeepModeling 是社区主页而非商业产品，
申请理由不占优势。手动发布可控性更好，文案质量也更容易把控。

---

## 规划：在现有工作流里加入领英步骤

### 新增 Step 7（在 GitHub PR 之后）

现有流水线是 6 步，在 Step 6（GitHub PR）之后加：

```
[Step 7/7] 生成领英动态文案
   用 LLM 基于 _en.md 和博客文件生成文案
   展示文案 → 用户确认/编辑 → 复制粘贴手动发布
```

### 实现要点

LLM 生成文案时需要喂：
- 博客 markdown 全文（包含图表说明和性能数据段，不能只用摘要）
- 博客链接（`https://blogs.deepmodeling.com/{CATEGORY}_{YYYY}_{MM}_{DD}/`）
- 格式规范（`data/linkedin-post-format.md`）

输出直接打印到终端，用户看完复制到领英粘贴发布。

### 何时加入自动化

满足以下任一条件时可以考虑接 API：
- DeepModeling LinkedIn 主页管理员愿意申请 Marketing API 产品权限
- 找到可靠的第三方发布工具（Buffer、Hootsuite 等）且有 API key

---

## 完整工作流（目标状态）

```
Step 1  下载微信文章
Step 2  LLM 翻译（断点：确认/跳过）
Step 3  保存 _en.md
Step 4  OSS 上传图片（断点：确认/跳过）
Step 5  格式转换生成博客 md
Step 6  提交 GitHub PR（断点：确认/跳过）
---- 人工：在 GitHub 上 review Files changed，Squash and merge ----
Step 7  LLM 生成领英文案（断点：展示文案，用户确认后复制粘贴发布）
```

Step 7 的"断点"和前面几步一样——展示内容、等用户按 1 确认，不需要用户
知道有这一步存在，流水线自然流过去。
