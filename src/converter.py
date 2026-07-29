"""
格式转换模块 - 将翻译输出转换为博客 Markdown 格式
====================================================
功能:
- 解析翻译后的英文 Markdown
- 清理翻译器元数据（来源块、警告等）
- LLM 自动分类（categories）
- 图片语法转换: ![](local) → <center><img src=url /></center>
- 生成 YAML frontmatter
- 插入 <!-- more --> 摘要分隔标记
"""

import os
import re
import sys
import yaml
from datetime import date
from openai import OpenAI
from typing import Dict, Optional, List, Tuple

from utils import (
    resolve_llm_config, clean_llm_response, find_file_by_suffix,
)

# 设置输出编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


# ---------------------------------------------------------------------------
# 已知分类列表（从现有博客中提取，供 LLM 参考）
# ---------------------------------------------------------------------------
KNOWN_CATEGORIES = [
    "ABACUS", "APEX", "DeePMD-kit", "DeePMD", "DeepFlame",
    "DeepSPIN", "DeePTB", "DFlow", "DPA", "GPUMD&NEP",
    "JAX-FEM", "LibRI", "OpenLAM", "ReacNetGenerator", "SciAssess",
    "TBPLaS", "Tutorials@Notebooks", "Uni-Lab", "Uni-Mol",
    "dftio", "tutorial", "Other",
]


class BlogConverter:
    """将翻译输出转换为 deepmodeling/blog 格式"""

    def __init__(self, config_path: str = None, llm_name: str = None,
                 model_name: str = None):
        """
        参数:
            config_path: config.yaml 路径，默认项目根目录
            llm_name:   LLM 提供商名称，不传则用 default
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

        print(f"✓ 转换器初始化完成")
        print(f"  - Provider: {self.provider_name}")
        print(f"  - API: {provider['base_url']}")
        print(f"  - Model: {self.model}")

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _load_config(self, config_path: str) -> dict:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _resolve_llm_config(self, llm_name: str = None) -> dict:
        """解析 LLM 配置（委托 utils.resolve_llm_config，支持新旧格式）"""
        return resolve_llm_config(self.config, llm_name)

    def _clean_response(self, content: str) -> str:
        """去除 LLM 可能包裹的代码块标记（委托 utils.clean_llm_response）"""
        return clean_llm_response(content)

    # ------------------------------------------------------------------
    # 核心转换流程
    # ------------------------------------------------------------------

    def convert_article(
        self,
        article_dir: str,
        output_dir: str = None,
        post_date: str = None,
        category: str = None,
    ) -> str:
        """
        转换一篇翻译后的文章为博客格式。

        参数:
            article_dir: 翻译输出目录（包含 _en.md, .images_map.txt, images/）
            output_dir:  博客格式输出目录（默认 article_dir 同级）
            post_date:   发布日期 YYYY-MM-DD（默认今天）
            category:    文章分类（如已在上游确定，传此参数跳过 LLM 分类）

        返回:
            输出文件路径
        """
        article_dir = os.path.abspath(article_dir)

        # ---- 定位输入文件 ----
        en_file = self._find_file(article_dir, '_en.md')
        map_file = self._find_file(article_dir, '.images_map.txt')

        if not en_file:
            raise FileNotFoundError(f"找不到 _en.md 文件: {article_dir}")
        if not map_file:
            print(f"  ⚠️ 未找到 images_map.txt，图片将保留本地路径")

        # ---- 解析 ----
        title, body = self._parse_translation(en_file)
        image_map = self._parse_image_map(map_file) if map_file else {}

        # ---- 清理 & 转换 ----
        body = self._strip_metadata_blockquotes(body)
        body = self._convert_latex_to_html(body)
        body = self._convert_images(body, image_map)
        body = self._fix_figure_labels(body)
        body = self._fix_image_layout(body)
        body = self._insert_more_tag(body)

        # ---- LLM 分类（如上游已确定则跳过） ----
        if category:
            print(f"  🏷 分类结果: {category} (复用)")
        else:
            category = self.classify_category(title, body)
            print(f"  🏷 分类结果: {category}")

        # ---- 生成输出 ----
        if post_date is None:
            post_date = date.today().isoformat()

        frontmatter = self._build_frontmatter(title, post_date, category, body)
        output = f"{frontmatter}\n{body}"

        # ---- 写入文件 ----
        if output_dir is None:
            output_dir = os.path.join(article_dir, 'blog_output')
        os.makedirs(output_dir, exist_ok=True)

        # 文件名格式: {CATEGORY}_{YYYY}_{MM}_{DD}.md
        filename = self._make_filename(category, post_date)
        output_path = os.path.join(output_dir, filename)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(output)

        print(f"  ✓ 输出: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # 文件定位
    # ------------------------------------------------------------------

    def _find_file(self, directory: str, suffix: str) -> Optional[str]:
        """在目录中查找以 suffix 结尾的文件（委托 utils.find_file_by_suffix）"""
        return find_file_by_suffix(directory, suffix)

    # ------------------------------------------------------------------
    # 解析翻译输出
    # ------------------------------------------------------------------

    def _parse_translation(self, en_file: str) -> Tuple[str, str]:
        """
        解析 _en.md 文件，返回 (title, body)。

        期望格式:
            # English Title Here
            > Source: ...
            > Translated by ...
            > Quality score: ...
            ---
            > Source: ...
            > ⚠️ ...
            ---
            Body content...
        """
        with open(en_file, 'r', encoding='utf-8') as f:
            text = f.read()

        lines = text.split('\n')
        title = ""
        body_start = 0

        # 提取 h1 标题（第一行 # ）
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('# ') and not title:
                title = stripped[2:].strip()
                body_start = i + 1
                break

        if not title:
            # fallback: 用文件名
            title = os.path.splitext(os.path.basename(en_file))[0]
            # 去掉 _en 后缀
            if title.endswith('_en'):
                title = title[:-3]

        body = '\n'.join(lines[body_start:]).strip()

        return title, body

    def _parse_image_map(self, map_file: str) -> Dict[str, str]:
        """
        解析 .images_map.txt，返回 {local_name: remote_url}。

        文件格式:
            # 注释行
            img_001 | https://mmbiz.qpic.cn/...
            img_002 | https://...
        """
        mapping = {}
        with open(map_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '|' in line:
                    key, url = line.split('|', 1)
                    mapping[key.strip()] = url.strip()
        print(f"  📷 图片映射: {len(mapping)} 张")
        return mapping

    # ------------------------------------------------------------------
    # 内容清理
    # ------------------------------------------------------------------

    def _strip_metadata_blockquotes(self, body: str) -> str:
        """
        删除翻译器添加的元数据块。

        移除:
            - 开头的 > Source / > Original title / > Translated by / > Quality score
            - 独立的 > ⚠️ 警告行
            - 翻译器添加的分隔线（元数据之后第一条 ---）
        """
        lines = body.split('\n')
        kept: List[str] = []
        in_metadata = True

        for line in lines:
            stripped = line.strip()

            # 检测元数据 blockquote 行
            if in_metadata:
                if stripped.startswith('> Source:') or \
                   stripped.startswith('> Original title:') or \
                   stripped.startswith('> Translated by') or \
                   stripped.startswith('> Quality score:') or \
                   stripped.startswith('> ⚠️') or \
                   stripped == '>':
                    continue
                # 元数据区域内的分隔线
                if stripped == '---':
                    continue
                # 元数据区域内的空行
                if stripped == '':
                    continue

            # 遇到正文内容，退出元数据模式
            if in_metadata and stripped:
                in_metadata = False

            kept.append(line)

        # 清理开头多余的空白
        while kept and kept[0].strip() == '':
            kept.pop(0)

        return '\n'.join(kept)

    # ------------------------------------------------------------------
    # LaTeX 公式 → HTML（codecogs SVG 图片）
    # ------------------------------------------------------------------

    def _convert_latex_to_html(self, body: str) -> str:
        r"""
        将 LaTeX 公式转换为 codecogs SVG 图片，适用于不支持 MathJax 的博客。

        支持四种语法:
          $$...$$   → 块级居中 SVG
          \[...\]   → 块级居中 SVG（同 $$）
          \\(...\\) → 行内 SVG
        """
        import urllib.parse

        def _encode(latex: str) -> str:
            return urllib.parse.quote(latex.strip(), safe='')

        # 块级公式（居中显示）
        def _replace_display(m: re.Match) -> str:
            encoded = _encode(m.group(1))
            return (
                f'<center><img src="https://latex.codecogs.com/svg.image?'
                f'{encoded}" /></center>'
            )

        # $$...$$（支持跨行）
        body = re.sub(
            r'\$\$\s*(.+?)\s*\$\$',
            _replace_display, body, flags=re.DOTALL,
        )
        # \[...\]（支持跨行，部分 LLM 会生成这种格式）
        body = re.sub(
            r'\\\[\s*(.+?)\s*\\\]',
            _replace_display, body, flags=re.DOTALL,
        )

        # 行内公式 \(...\)
        def _replace_inline(m: re.Match) -> str:
            encoded = _encode(m.group(1))
            return (
                f'<img src="https://latex.codecogs.com/svg.image?\\inline '
                f'{encoded}" style="vertical-align:middle" />'
            )

        body = re.sub(r'\\\(\s*(.+?)\s*\\\)', _replace_inline, body)

        return body

    # ------------------------------------------------------------------
    # 图片转换: ![alt](images/xxx.png) → <center><img src=url /></center>
    # ------------------------------------------------------------------

    def _convert_images(self, body: str, image_map: Dict[str, str]) -> str:
        """
        将 Markdown 图片语法转换为博客 HTML 格式。

        输入:  ![图1](images/img_001.png)
        输出:  <center><img src=https://... pic_center width="100%" height="100%" /></center>
        """

        def replace_img(match: re.Match) -> str:
            alt = match.group(1)
            local_path = match.group(2)
            local_name = os.path.splitext(os.path.basename(local_path))[0]

            # 查找远程 URL
            remote_url = image_map.get(local_name, local_path)
            return (
                f'<center><img src={remote_url}'
                f' pic_center width="100%" height="100%" /></center>'
            )

        # 匹配 ![alt](path)  —— 不匹配已经是 HTML 的 <img
        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        return re.sub(pattern, replace_img, body)

    # ------------------------------------------------------------------
    # <!-- more --> 插入
    # ------------------------------------------------------------------

    def _insert_more_tag(self, body: str) -> str:
        """
        在第一个实质性段落之后插入 <!-- more --> 标记。

        策略:
            跳过 frontmatter 和标题行，在第一个非空段落结束后插入。
            段落定义为：至少 80 个字符的长文本行，或连续多行组成的段落。
        """
        lines = body.split('\n')
        output: List[str] = []
        chars_collected = 0
        more_inserted = False
        empty_since_content = 0

        for line in lines:
            stripped = line.strip()

            output.append(line)

            if more_inserted:
                continue

            # 跳过标题和图片行
            if stripped.startswith('#') or stripped.startswith('<center>') or \
               stripped.startswith('![') or stripped.startswith('>'):
                chars_collected = 0
                continue

            if stripped == '':
                if chars_collected >= 80:
                    # 段落结束，插入 more
                    output.append('')
                    output.append('<!-- more -->')
                    more_inserted = True
                chars_collected = 0
                continue

            chars_collected += len(stripped)

        # 如果文章很短，没找到合适的插入点，放在第 5 行之后
        if not more_inserted and len(output) > 5:
            output.insert(5, '')
            output.insert(6, '<!-- more -->')
            output.insert(7, '')

        return '\n'.join(output)

    # ------------------------------------------------------------------
    # LLM 分类
    # ------------------------------------------------------------------

    def classify_category(self, title: str, body: str) -> str:
        """
        使用 LLM 判断文章所属分类（公开接口，流水线可在上传前调用）。

        输入文章标题和前 1500 字内容，从已知分类中选出最合适的。
        如果都不匹配，LLM 可以建议新的分类名。
        """
        print(f"  🤖 正在调用 LLM 分类...")

        categories_list = '\n'.join(f"  - {c}" for c in KNOWN_CATEGORIES)

        system_prompt = f"""You classify DeepModeling community blog articles. Output ONLY the category name — no quotes, no punctuation, no explanation.

Existing categories:
{categories_list}

Classification guide:
- The article TITLE is the strongest signal — if it mentions a tool (e.g., "ABACUS", "DeePMD"), that is almost always the correct category
- Articles about Deep Potential / DP models / DeePMD → "DeePMD-kit"
- Articles about ABACUS software → "ABACUS"
- Articles about Uni-Mol molecular pretraining → "Uni-Mol"
- Articles about DeepFlame combustion → "DeepFlame"
- Articles about OpenLAM large atomic model → "OpenLAM"
- Articles about APEX alloy properties → "APEX"
- Articles about specific other tools → use that tool's category
- Only use "Other" if the article truly fits NONE of the existing categories (e.g., general community event, workshop report, non-tool news)

Key rule: classify based on what TOOL/SOFTWARE the article is about, not the scientific domain. The TITLE takes priority over body content when they conflict. An article using DP for materials science → "DeePMD-kit", not "Other".

Remember: You MUST output exactly one category name. DO NOT output an empty response."""

        # 截取前 3000 字符（中文信息密度高，需更宽窗口覆盖工具名出现位置）
        excerpt = body[:3000]

        user_prompt = f"""Classify this article:

**Title**: {title}

**Content excerpt**:
{excerpt}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=200,
            )

            category = response.choices[0].message.content.strip()
            category = self._clean_response(category)
            # 去除可能的引号包裹
            category = category.strip('"').strip("'").strip()

            return category if category else "Other"

        except Exception as e:
            print(f"  ⚠️ LLM 分类失败 ({e})，回退为 'Other'")
            return "Other"

    # ------------------------------------------------------------------
    # Frontmatter 生成
    # ------------------------------------------------------------------

    def _build_frontmatter(self, title: str, post_date: str,
                           category: str, body: str) -> str:
        """生成 YAML frontmatter 块，仅当文章含数学公式时才加 mathjax: true"""
        safe_title = title.replace('"', '\\"')
        has_math = self._has_math_formula(body)

        lines = [
            '---',
            f'title: "{safe_title}"',
            f'date: {post_date}',
            'categories:',
            f'- {category}',
        ]
        if has_math:
            lines.append('mathjax: true')
        lines.append('---')
        lines.append('')

        return '\n'.join(lines)

    def _has_math_formula(self, body: str) -> bool:
        """检测文章是否包含 LaTeX 数学公式"""
        # $$...$$ 块级公式
        if '$$' in body:
            return True
        # $...$ 行内公式（排除无效模式）
        inline = re.findall(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', body)
        return len(inline) > 0

    # ------------------------------------------------------------------
    # 文件名生成
    # ------------------------------------------------------------------

    @staticmethod
    def make_oss_folder(category: str, post_date: str) -> str:
        """
        生成 OSS 上传文件夹名: {CATEGORY}_{YYYY}_{MM}_{DD}

        例如: DeePMD-kit_2026_07_14
        """
        parts = post_date.split('-')
        if len(parts) == 3:
            yyyy, mm, dd = parts[0], parts[1], parts[2]
            return f"{category}_{yyyy}_{mm}_{dd}"
        return f"{category}_{post_date}"

    def _make_filename(self, category: str, post_date: str) -> str:
        """生成博客文件名: {CATEGORY}_{YYYY}_{MM}_{DD}.md"""
        return f"{self.make_oss_folder(category, post_date)}.md"

    # ------------------------------------------------------------------
    # 图片排版修复
    # ------------------------------------------------------------------

    def _fix_figure_labels(self, body: str) -> str:
        """
        将翻译后正文中残留的中文图注标签 图N 替换为 Figure N。

        只替换行首或紧跟空格出现的 图N（不影响 URL 和文件名中的 '图' 字）。
        """
        def replace_label(m: re.Match) -> str:
            return f"Figure {m.group(1)}"

        # 匹配：行首 或 空格+图+数字（1-2位），后面跟空格或英文
        body = re.sub(r'(?<=^)图(\d{1,2})(?=[\sA-Z])', replace_label, body,
                      flags=re.MULTILINE)
        body = re.sub(r'(?<=\s)图(\d{1,2})(?=[\sA-Z])', replace_label, body)
        return body

    def _fix_image_layout(self, body: str) -> str:
        """
        修复图片排版问题：

        1. 每个 <center><img ... /></center> 独立成行
        2. 图片之间的 **粗体文本** 转为 ## 二级标题（如果像章节名）
        """
        lines = body.split('\n')
        fixed: List[str] = []

        for line in lines:
            stripped = line.strip()

            # 如果这一行包含 <center> 图片标签
            if '<center><img' in stripped:
                # 把图片和文字拆分到独立行
                # 匹配: <center><img ... /></center>
                img_pattern = r'(<center><img\s[^>]*?/>\s*</center>)'
                parts = re.split(img_pattern, stripped)

                for part in parts:
                    part = part.strip()
                    if not part:
                        continue
                    if part.startswith('<center><img'):
                        # 图片独立成行
                        fixed.append(part)
                    else:
                        # 非图片文本：如果是加粗短文本，转 ## 标题
                        part = self._inline_text_to_heading(part)
                        if part:
                            fixed.append(part)
            else:
                fixed.append(line)

        return '\n'.join(fixed)

    def _inline_text_to_heading(self, text: str) -> str:
        """
        将图片之间夹着的加粗文本转为 Markdown 标题。

        微信文章常用: ![图]bold标题![图] 来模拟章节分隔，
        博客格式应该用 ## 标题。
        """
        text = text.strip()
        if not text:
            return text

        # 去掉所有 ** 包裹（支持 **, ****, ****** 等变体）
        had_bold = False
        while text.startswith('**') and text.endswith('**'):
            had_bold = True
            # 去掉首尾的一层 **
            if text.startswith('****'):
                text = text[4:]
            elif text.startswith('**'):
                text = text[2:]
            if text.endswith('****'):
                text = text[:-4]
            elif text.endswith('**'):
                text = text[:-2]
            text = text.strip()

        if had_bold:
            # 夹在图片之间的加粗文本 = 章节标题
            return f'## {text}'

        # 没有加粗标记的短文本：可能仍是标题
        if len(text) <= 60 and not text.startswith('<'):
            return f'## {text}'

        return text


# ===================================================================
# 命令行入口
# ===================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='将翻译输出转换为 deepmodeling/blog 格式',
    )
    parser.add_argument(
        '--dir', required=True,
        help='翻译输出目录（如 output/article_20260714_145600）',
    )
    parser.add_argument(
        '--output', default=None,
        help='博客格式输出目录（默认在输入目录下创建 blog_output/）',
    )
    parser.add_argument(
        '--date', default=None,
        help='发布日期 YYYY-MM-DD（默认今天）',
    )
    parser.add_argument(
        '--llm', default=None,
        help='LLM 提供商（qwen / deepseek），默认使用 config.yaml 中的 default',
    )
    parser.add_argument(
        '--model', default=None,
        help='覆盖模型名（默认用 config.yaml 中该提供商的 model_name）',
    )
    parser.add_argument(
        '--config', default=None,
        help='配置文件路径（默认项目根目录 config.yaml）',
    )

    args = parser.parse_args()
    converter = BlogConverter(config_path=args.config, llm_name=args.llm,
                              model_name=args.model)
    converter.convert_article(
        article_dir=args.dir,
        output_dir=args.output,
        post_date=args.date,
    )


if __name__ == '__main__':
    main()
