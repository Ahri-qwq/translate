"""
翻译模块 - 调用 API 翻译 Markdown 内容
================================
功能:
- 读取 config.yaml 中的 API 配置
- 翻译中文 Markdown 到英文
- 保留公式、图片链接、特殊格式
- LLM 审核翻译质量
"""

import os
import re
import sys
import json
import yaml
from openai import OpenAI
from typing import Tuple, Dict, Optional

from utils import resolve_llm_config, clean_llm_response

# 设置输出编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


class Translator:
    """API 翻译器 + 审核器"""
    
    def __init__(self, config_path: str = None, llm_name: str = None,
                 model_name: str = None):
        """
        初始化翻译器

        参数:
            config_path: 配置文件路径，默认为项目根目录的 config.yaml
            llm_name:   LLM 提供商名称（如 qwen / deepseek），不传则用 default
            model_name: 模型名覆盖（不传则用 config.yaml 中的默认值）
        """
        if config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            config_path = os.path.join(project_root, "config.yaml")

        self.config = self._load_config(config_path)
        provider = self._resolve_llm_config(llm_name)

        # --model 参数可覆盖配置中的 model_name
        self.model = model_name or provider['model_name']
        self.provider_name = provider.get('name', 'unknown')

        self.client = OpenAI(
            api_key=provider['api_key'],
            base_url=provider['base_url'],
        )

        print(f"✓ 翻译器初始化完成")
        print(f"  - Provider: {self.provider_name}")
        print(f"  - API: {provider['base_url']}")
        print(f"  - Model: {self.model}")
    
    def _load_config(self, config_path: str) -> dict:
        """加载 YAML 配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _resolve_llm_config(self, llm_name: str = None) -> dict:
        """解析 LLM 配置（委托 utils.resolve_llm_config，支持新旧格式）"""
        return resolve_llm_config(self.config, llm_name)

    # 推理模型（deepseek-v4-pro / qwen3.7-max 等）的 max_tokens 是
    # 思维链 + 正文的共享预算。设太小会出现思维链吃光额度、正文为空
    # 的情况（finish_reason='length'，content 为空串）。
    MAX_TOKENS_LONG = 64000   # 翻译 / 修改：需要完整输出长文
    MAX_TOKENS_JSON = 32000   # 审核：只输出 JSON，但思维链同样占额度

    @staticmethod
    def _extract_content(response, stage: str) -> str:
        """
        从 API 响应中取正文，并校验它确实可用。

        推理模型可能把 max_tokens 全部花在思维链上，返回
        finish_reason='length' 且 content 为空。这种情况必须当成
        错误抛出，否则空串会一路写进文件、覆盖掉好内容。
        """
        choice = response.choices[0]
        content = choice.message.content or ''
        finish = choice.finish_reason

        usage = getattr(response, 'usage', None)
        reasoning = None
        if usage is not None:
            details = getattr(usage, 'completion_tokens_details', None)
            reasoning = getattr(details, 'reasoning_tokens', None)

        if not content.strip():
            hint = ''
            if finish == 'length':
                hint = (f'（思维链占用 {reasoning} tokens，耗尽了 max_tokens 额度；'
                        f'请调大 max_tokens 或改用非推理模型）')
            raise RuntimeError(
                f'{stage}: 模型返回空内容 [finish_reason={finish}]{hint}'
            )

        if finish == 'length':
            print(f'   ⚠️ {stage}: 输出被 max_tokens 截断，内容可能不完整'
                  f'（reasoning_tokens={reasoning}）')

        return content

    def _restore_heading_levels(self, zh: str, en: str) -> str:
        """
        校正译文的标题层级，使之与原文一一对应。

        模型有时会丢掉开头那行 # 文章标题，并把正文第一个 ## 提升成 #
        来满足「输出必须以 # 开头」的要求。同一份输入重复调用，有时正常
        有时出错——纯靠 prompt 约束不住，所以在代码里兜底。

        做法：按出现顺序逐个比对标题层级；数量一致时直接按原文层级改写，
        数量不一致说明模型增删了标题，只修正开头被提升的那一个，其余
        保持原样（宁可少改，也不要错改）。
        """
        pat = re.compile(r'^(#{1,6})[ 	]+(.*\S)[ 	]*$')

        def scan(text):
            hits, in_code = [], False
            for i, line in enumerate(text.split('\n')):
                if line.lstrip().startswith('```'):
                    in_code = not in_code
                    continue
                if in_code:
                    continue
                m = pat.match(line)
                if m:
                    hits.append((i, len(m.group(1)), m.group(2)))
            return hits

        zh_h, en_h = scan(zh), scan(en)
        if not zh_h or not en_h:
            return en

        lines = en.split('\n')

        if len(zh_h) == len(en_h):
            # 数量对得上：逐个把层级校正回原文的层级
            fixed = 0
            for (_, zh_lv, _), (idx, en_lv, text) in zip(zh_h, en_h):
                if zh_lv != en_lv:
                    lines[idx] = f"{'#' * zh_lv} {text}"
                    fixed += 1
            if fixed:
                print(f"   🔧 已校正 {fixed} 处标题层级")
            # 层级和数量都对，但模型可能整行照抄没翻译（标题保持中文）。
            # 这种情况前面的比对完全看不出来，得单独查一次首行标题。
            idx, lv, text = en_h[0]
            if lv == 1 and self._has_cjk(text):
                en_title = self._translate_title(zh_h[0][2])
                if en_title and not self._has_cjk(en_title):
                    lines[idx] = f'# {en_title}'
                    print("   🔧 文章标题未翻译，已补译")
                else:
                    print("   ⚠️ 文章标题仍是中文，补译未成功")
            return '\n'.join(lines)

        # 数量对不上：最常见的情况是模型吞掉了开头的 # 文章标题。
        # 此时译文的标题序列应当与原文「去掉第一个」之后对齐；把剩下的
        # 逐个按原文层级校正（模型往往还会把首个 ## 提升成 #）。
        if len(en_h) == len(zh_h) - 1 and zh_h[0][1] == 1:
            fixed = 0
            for (_, zh_lv, _), (idx, en_lv, text) in zip(zh_h[1:], en_h):
                if zh_lv != en_lv:
                    lines[idx] = f"{'#' * zh_lv} {text}"
                    fixed += 1
            # 补回缺失的标题行：单独翻一次原文标题，插到最前面。
            # 拿不到译文时留空，交给 main.py 回退中文原标题。
            en_title = self._translate_title(zh_h[0][2])
            if en_title:
                lines.insert(0, f'# {en_title}')
                lines.insert(1, '')
                print(f"   🔧 译文缺少文章标题行，已补译标题"
                      f"并校正 {fixed} 处层级")
            else:
                print(f"   🔧 已校正 {fixed} 处标题层级（标题行仍缺失）")
            return '\n'.join(lines)

        print(f"   ⚠️ 标题数量不一致（原文 {len(zh_h)} / 译文 {len(en_h)}），未自动校正")
        return en

    @staticmethod
    def _has_cjk(text: str) -> bool:
        """文本里是否含中日韩表意文字（用来判断标题有没有真的翻译）。"""
        return any('一' <= ch <= '鿿' for ch in text)

    def _translate_title(self, zh_title: str) -> str:
        """
        单独翻译文章标题。

        整篇翻译时模型偶尔会吞掉开头的 # 标题行（改用正文小标题顶替），
        此时补一次只翻标题的小请求，比让整篇重跑便宜得多。
        失败就返回空串，由调用方决定回退策略。
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content":
                        "You translate Chinese article titles into English. "
                        "Output ONLY the translated title as plain text: no "
                        "quotes, no Markdown, no explanation. "
                        "Many titles have two parts: a colloquial hook question "
                        "plus a technical subtitle. Translate BOTH. Keep the hook "
                        "punchy: 'X还能干这个？' becomes 'What Can X Do Too?' "
                        "(house style). Never flatten the pair into one dry "
                        "technical phrase and never drop the hook."},
                    {"role": "user", "content": zh_title},
                ],
                temperature=0.3,
                max_tokens=self.MAX_TOKENS_JSON,
            )
            en_title = (response.choices[0].message.content or '').strip()
            # 模型可能仍然带上 # 或引号，清掉
            en_title = en_title.lstrip('#').strip().strip('"').strip()
            return en_title.split('\n')[0].strip()
        except Exception as e:
            print(f"   ⚠️ 标题补译失败: {e}")
            return ''

    def translate_markdown(self, markdown_content: str, title: str = None) -> str:
        """
        翻译 Markdown 内容
        
        参数:
            markdown_content: 中文 Markdown 内容
            title: 文章标题（可选，用于更好的翻译）
            
        返回:
            英文 Markdown 内容
        """
        print(f"\n🔄 正在翻译...")
        print(f"   - 内容长度: {len(markdown_content)} 字")
        
        # 构建翻译提示
        system_prompt = """You are a professional translator specializing in translating Chinese technical articles to English.

Your task:
1. Translate ALL Chinese text to English, INCLUDING headings and the article title.
2. Preserve formatting:
   - Keep LaTeX formulas unchanged: $$...$$ and \\(...\\)
   - Keep image links EXACTLY as-is — DO NOT touch them at all:
     Example: ![图4](images/img_004.png) stays as ![图4](images/img_004.png)
   - Keep all URLs unchanged
   - Keep Markdown markup (#, **, >, etc.) — translate only the text
3. Keep technical terms accurate (don't over-translate domain-specific terms)
4. Maintain the original tone and style

TITLE — keep the hook:
- A common Chinese science-blog title has TWO parts: a colloquial hook question
  followed by a dry technical subtitle, e.g.
    "DP还能干这个？深度学习势揭示AgPd纳米合金表面位错形核与原子重排机制"
- Translate BOTH parts. The hook becomes an equally punchy English question,
  the subtitle stays a technical noun phrase.
- "X还能干这个？" → "What Can X Do Too?" (keep this phrasing — it is the
  house style for this blog).
- Other hooks: "没想到吧？" → "Who Knew?", "原来还能这样？" → "So It Can Do That Too?",
  "万万没想到" → "Never Saw That Coming".
- NEVER flatten a two-part title into a single dry technical phrase, and never
  drop the hook. Example of the expected result:
    "What Can DP Do Too? Deep Learning Potential Reveals Surface Dislocation
     Nucleation and Atomic Rearrangement in AgPd Nanoalloys"

CRITICAL — headings:
- The source begins with a single `# ` line: that is the ARTICLE TITLE. Translate it
  and keep it as the first line of your output.
- NEVER drop the article title and promote a `## ` section heading to `# ` in its place.
- Keep EVERY heading at its ORIGINAL level: `# ` stays `# `, `## ` stays `## `,
  `### ` stays `### `. Do not add, remove, merge, or re-level any heading.
- The output must contain exactly as many heading lines as the input, in the same order.
- `#` characters inside ``` code blocks are shell comments, NOT headings — leave them alone.

Output ONLY the translated Markdown, no explanations."""

        user_prompt = f"""Translate this Chinese Markdown article to English.

The content below starts with a # heading. You MUST translate that heading and keep it as the first line of your output.

Content:
{markdown_content}

REMEMBER: Start your output with # <translated title>. Output pure Markdown only (no code blocks wrapping it)."""

        # 调用 API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,  # 低温度保证翻译稳定
                max_tokens=self.MAX_TOKENS_LONG,
            )
            
            translated_content = self._extract_content(response, '翻译')
            
            # 清理可能的包装
            translated_content = self._clean_response(translated_content)

            # 兜底：模型可能吞掉标题行 / 改动标题层级
            translated_content = self._restore_heading_levels(
                markdown_content, translated_content
            )
            
            print(f"   ✓ 翻译完成: {len(translated_content)} 字")
            
            return translated_content
            
        except Exception as e:
            print(f"   ❌ 翻译失败: {e}")
            raise
    
    def _clean_response(self, content: str) -> str:
        """清理 API 返回内容（委托 utils.clean_llm_response）"""
        return clean_llm_response(content)
    
    # ------------------------------------------------------------------
    # 交叉审查客户端
    # ------------------------------------------------------------------

    def _get_review_config(self):
        """读取审查配置"""
        return self.config.get('review', {})

    def _get_reviewer_client(self) -> Optional[OpenAI]:
        """获取第二个审查模型的客户端（懒加载）"""
        review_cfg = self._get_review_config()
        if not review_cfg.get('cross_review'):
            return None

        second = review_cfg.get('second_reviewer', '')
        if not second:
            return None

        try:
            provider = self._resolve_llm_config(second)
            return OpenAI(
                api_key=provider['api_key'],
                base_url=provider['base_url'],
            )
        except Exception:
            return None

    def _cross_review(self, zh_content: str, en_content: str,
                      title: str = None) -> Dict:
        """
        双模型交叉审查：主模型 + 第二模型独立审查，合并报告。

        返回: 合并后的审查报告（取较低的分数、合并去重的问题列表）
        """
        review_cfg = self._get_review_config()

        # 主模型审查
        primary = self.review_translation(zh_content, en_content, title)

        # 第二模型审查
        reviewer_client = self._get_reviewer_client()
        if reviewer_client is None:
            return primary

        second_model = review_cfg.get('second_reviewer', '?')
        print(f"\n🔍 交叉审查: 第二模型 ({second_model}) 独立审查...")

        try:
            secondary = self._review_with_client(
                reviewer_client, zh_content, en_content, title
            )

            # 合并：得分取最低
            merged = {
                'passed': primary['passed'] and secondary['passed'],
                'score': min(primary.get('score', 100),
                             secondary.get('score', 100)),
                'issues': self._merge_issues(
                    primary.get('issues', []),
                    secondary.get('issues', []),
                ),
                'suggestions': list(dict.fromkeys(
                    primary.get('suggestions', []) +
                    secondary.get('suggestions', [])
                )),
            }

            print(f"   - 主模型: {primary.get('score')}/100, "
                  f"{len(primary.get('issues', []))} 问题")
            print(f"   - 第二模型: {secondary.get('score')}/100, "
                  f"{len(secondary.get('issues', []))} 问题")
            print(f"   - 合并: {merged['score']}/100, "
                  f"{len(merged['issues'])} 问题")

            return merged

        except Exception as e:
            print(f"   ⚠️ 第二模型审查失败 ({e})，仅使用主模型结果")
            return primary

    def _review_with_client(self, client: OpenAI, zh_content: str,
                            en_content: str, title: str = None) -> Dict:
        """用指定客户端执行审查（与 review_translation 相同逻辑，但用外部 client）"""
        import json

        system_prompt = """You are a professional translation reviewer specializing in Chinese-English technical translation.

Your task is to review the translation and identify ONLY SIGNIFICANT issues.

## Review Guidelines

1. **Missing Translation** (ONLY report if entire paragraphs/sections are missing)
2. **Terminology Inconsistency** (ONLY for critical technical terms)
3. **Format Issues** (ONLY for broken content)
4. **Accuracy Issues** (ONLY for significant errors)
5. **Style Issues** (generally ignore, unless extremely awkward)

Output a JSON object with this structure:
{
    "passed": true/false,
    "score": 0-100,
    "issues": [
        {"type": "missing|terminology|format|accuracy|style", "location": "...", "description": "..."}
    ],
    "suggestions": ["suggestion1", "suggestion2", ...]
}

Be practical and lenient. Most translations should pass with score >= 70."""

        truncated = '...(end truncated for review)' if len(zh_content) > 8000 else ''
        zh_preview = zh_content[:8000] + truncated
        en_preview = en_content[:8000] + truncated

        user_prompt = f"""Review this Chinese to English translation.

**Article Title**: {title if title else 'Unknown'}

Note: If content is truncated for length, only review what is shown. Do NOT flag truncation as a missing translation.

**Chinese Original** ({len(zh_content)} total chars):
<CHINESE_ORIGINAL>
{zh_preview}
</CHINESE_ORIGINAL>

**English Translation** ({len(en_content)} total chars):
<ENGLISH_TRANSLATION>
{en_preview}
</ENGLISH_TRANSLATION>

Output ONLY the JSON review result."""

        response = client.chat.completions.create(
            model=self._resolve_llm_config(
                self._get_review_config().get('second_reviewer', '')
            )['model_name'],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=self.MAX_TOKENS_JSON,
        )

        result_text = clean_llm_response(response.choices[0].message.content)
        return json.loads(result_text)

    @staticmethod
    def _merge_issues(primary: list, secondary: list) -> list:
        """合并两份审查的问题列表，按类型+位置去重"""
        seen = set()
        merged = []
        for issue in primary + secondary:
            key = (
                issue.get('type', '') + '|' +
                issue.get('location', '') + '|' +
                issue.get('description', '')[:80]
            )
            if key not in seen:
                seen.add(key)
                merged.append(issue)
        return merged

    def review_translation(self, zh_content: str, en_content: str,
                           title: str = None) -> Dict:
        """
        审核翻译质量
        
        参数:
            zh_content: 中文原文
            en_content: 英文译文
            title: 文章标题
            
        返回:
            {
                'passed': bool,           # 是否通过审核
                'score': int,             # 质量分数 (0-100)
                'issues': list,           # 问题列表
                'suggestions': list,      # 改进建议
                'revised_content': str    # 修正后的内容（如有重大问题）
            }
        """
        print(f"\n🔍 正在审核翻译质量...")
        
        system_prompt = """You are a professional translation reviewer specializing in Chinese-English technical translation.

Your task is to review the translation and identify ONLY SIGNIFICANT issues.

## Review Guidelines

1. **Missing Translation** (ONLY report if entire paragraphs/sections are missing)
   - DO NOT report minor omissions
   - Compare section count and structure, not exact word count

2. **Terminology Inconsistency** (ONLY for critical technical terms)
   - Same technical term should be translated consistently
   - Example: "密度泛函理论" should always be "DFT" or "density functional theory"

3. **Format Issues** (ONLY for broken content)
   - Broken LaTeX formulas: $$ should be preserved
   - Missing critical content due to format errors
   - DO NOT report image labels (like "图1" vs "Figure 1") - this is intentional

4. **Accuracy Issues** (ONLY for significant errors)
   - Wrong technical meaning
   - Incorrect numbers or units
   - DO NOT report minor style preferences

5. **Style Issues** (generally ignore, unless extremely awkward)
   - Minor awkward phrasing is acceptable
   - Focus on clarity, not elegance

## Important Rules

- Image labels like "![图1]" should NOT be translated to "![Figure 1]" - this is intentional for easy reference
- Technical article translations prioritize accuracy over style
- A score >= 70 means acceptable quality
- Only report issues that would confuse readers or convey wrong information

Output a JSON object with this structure:
{
    "passed": true/false,
    "score": 0-100,
    "issues": [
        {"type": "missing|terminology|format|accuracy|style", "location": "...", "description": "..."}
    ],
    "suggestions": ["suggestion1", "suggestion2", ...]
}

CRITICAL: Your job is ONLY to review and score. Do NOT output revised content. Do NOT rewrite the translation. Output ONLY the JSON review result.
Be practical and lenient. Most translations should pass with score >= 70."""

        # 截断过长的内容（LLM 上下文有限），但保留足够长度让审查可靠
        truncated = '...(end truncated for review)' if len(zh_content) > 8000 else ''
        zh_preview = zh_content[:8000] + truncated
        en_preview = en_content[:8000] + truncated

        user_prompt = f"""Review this Chinese to English translation.

**Article Title**: {title if title else 'Unknown'}

Note: If content is truncated for length, only review what is shown. Do NOT flag truncation as a missing translation.

**Chinese Original** ({len(zh_content)} total chars):
<CHINESE_ORIGINAL>
{zh_preview}
</CHINESE_ORIGINAL>

**English Translation** ({len(en_content)} total chars):
<ENGLISH_TRANSLATION>
{en_preview}
</ENGLISH_TRANSLATION>

Output ONLY the JSON review result."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                max_tokens=self.MAX_TOKENS_JSON,
            )
            
            # 解析 JSON（清理可能的 markdown 代码块包装）
            result_text = clean_llm_response(response.choices[0].message.content)
            result = json.loads(result_text)
            
            # 打印审核结果
            score = result.get('score', 0)
            passed = result.get('passed', False)
            issues = result.get('issues', [])
            
            print(f"   ✓ 审核完成")
            print(f"   - 质量分数: {score}/100")
            print(f"   - 通过状态: {'✅ 通过' if passed else '❌ 未通过'}")
            
            if issues:
                print(f"   - 发现问题: {len(issues)} 个")
                for i, issue in enumerate(issues[:3], 1):  # 只显示前3个
                    print(f"     [{i}] {issue.get('type', 'unknown')}: {issue.get('description', '')[:50]}")
                if len(issues) > 3:
                    print(f"     ... 还有 {len(issues) - 3} 个问题")
            
            return result
            
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"审核结果 JSON 解析失败（模型可能返回了空内容）: {e}"
            )
        except Exception as e:
            print(f"   ❌ 审核失败: {e}")
            return {
                'passed': True,
                'score': 70,
                'issues': [],
                'suggestions': [f'审核过程出错: {str(e)}'],
                'revised_content': None
            }
    
    def revise_translation(self, zh_content: str, en_content: str,
                            review: Dict, title: str = None) -> str:
        """
        根据审查报告修改译文（独立的 LLM 调用，专注修改不审查）。

        参数:
            zh_content: 中文原文
            en_content: 当前英文译文
            review:     审查报告（含 issues 和 suggestions）
            title:      文章标题
        返回:
            修改后的英文译文
        """
        # 构建审查发现的问题摘要
        issues_text = ""
        for i, issue in enumerate(review.get('issues', []), 1):
            issues_text += (
                f"  [{i}] {issue.get('type', '?')}: "
                f"{issue.get('description', '')}\n"
                f"       Location: {issue.get('location', 'N/A')}\n"
            )

        suggestions = review.get('suggestions', [])
        suggestions_text = '\n'.join(
            f"  - {s}" for s in suggestions
        ) if suggestions else "  (none)"

        print(f"\n🔧 正在根据审查报告修改译文...")
        print(f"   - 问题数: {len(review.get('issues', []))}")
        print(f"   - 建议数: {len(suggestions)}")

        system_prompt = """You are a professional translator specializing in Chinese-English technical translation.

Your task is to REVISE an English translation based on a review report. You are given:
1. The Chinese original
2. The current English translation
3. A review report listing specific issues and suggestions

Rules:
- Fix ONLY the issues listed in the review report. Do NOT rewrite the entire translation.
- Preserve ALL formatting: image links (![...](...)), LaTeX formulas ($$...$$), URLs, and Markdown markup.
- If the review says the title is not translated, make sure your output starts with a translated # heading.
- If the review says content is missing/truncated, check the Chinese original and add the missing sections.
- Maintain the same technical terminology as the original translation where correct.
- Do NOT change image labels or figure references.

Output ONLY the revised Markdown translation, no explanations."""

        user_prompt = f"""Revise this English translation based on the review report.

**Article Title**: {title if title else 'Unknown'}

**Review Issues**:
{issues_text}

**Review Suggestions**:
{suggestions_text}

**Chinese Original**:
<CHINESE_ORIGINAL>
{zh_content}
</CHINESE_ORIGINAL>

**Current English Translation**:
<ENGLISH_TRANSLATION>
{en_content}
</ENGLISH_TRANSLATION>

Output the complete revised English translation as pure Markdown (no code blocks)."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=self.MAX_TOKENS_LONG,
            )

            revised = self._extract_content(response, '修改译文')
            revised = self._clean_response(revised)

            print(f"   ✓ 修改完成: {len(revised)} 字")
            return revised

        except Exception as e:
            print(f"   ❌ 修改失败: {e}")
            raise

    def translate_with_review(self, markdown_content: str, title: str = None,
                               auto_fix: bool = True) -> Tuple[str, Dict]:
        """
        翻译 + 审核（一体化流程）
        
        参数:
            markdown_content: 中文 Markdown 内容
            title: 文章标题
            auto_fix: 是否自动应用修正（如果审核提供）
            
        返回:
            (最终译文, 审核结果)
        """
        # Step 1: 翻译
        en_content = self.translate_markdown(markdown_content, title)
        
        # Step 2: 审核（交叉审查或单模型审查）
        if self._get_review_config().get('cross_review'):
            review_result = self._cross_review(markdown_content, en_content, title)
        else:
            review_result = self.review_translation(markdown_content, en_content, title)
        
        # Step 3: 如需修正，调用独立的 revise LLM
        if not review_result.get('passed', True) and auto_fix:
            score = review_result.get('score', 0)
            issues = review_result.get('issues', [])
            if issues:
                try:
                    revised = self.revise_translation(
                        markdown_content, en_content, review_result, title
                    )
                    # 兜底：修改结果明显退化（空/大幅缩水）时保留原译文，
                    # 避免一次失败的 revise 把好译文覆盖掉。
                    if len(revised.strip()) < len(en_content.strip()) * 0.5:
                        print(f'   ⚠️ 修改结果异常（{len(revised)} 字 < 原文 '
                              f'{len(en_content)} 字的一半），保留原译文')
                        review_result['revised'] = False
                    else:
                        en_content = revised
                        review_result['revised'] = True
                except Exception as e:
                    print(f"   ⚠️ 修改失败 ({e})，使用原译文")
                    review_result['revised'] = False
            else:
                print(f"   审查未通过（{score}/100）但无具体问题，跳过修改")

        return en_content, review_result
    

def test_translator():
    """测试翻译器"""
    print("=" * 50)
    print("翻译器测试")
    print("=" * 50)
    
    translator = Translator()
    
    # 测试文本
    test_md = """# 这是一个测试标题

这是一段中文内容，包含一个公式：

$$
E = mc^2
$$

还有一张图片：

![图1](images/img_001.png)

最后是一些引用：

> 这是引用内容
"""
    
    result = translator.translate_markdown(test_md, "这是一个测试标题")
    
    print("\n" + "=" * 50)
    print("翻译结果:")
    print("=" * 50)
    print(result)


if __name__ == "__main__":
    test_translator()