"""
领英动态文案生成模块
====================
功能:
- 读取博客 Markdown 全文 + 格式规范
- 调用 LLM 生成领英动态文案
- 核对文案中的数字是否都能在博客里找到出处
- 输出纯文本 .txt（可直接复制到领英发布，无需再做格式处理）

为什么输出 .txt 而不是 .md:
    领英不渲染 Markdown（`#` 标题、`**` 加粗都是字面字符），发布时是直接
    粘贴纯文本。输出 .md 反而会让人以为格式会生效，且复制时容易连带把
    标记带进去。纯文本最省事，进去就能全选复制。

数字溯源:
    文案里的每个数字都必须出现在博客正文中。LLM 在写推广文案时有编造
    具体数值的倾向（尤其是"提升 X%"这类），而这类错误一旦发布出去就
    是公开的、需要撤回的。所以生成后逐个数核对一遍，对不上的打出来给
    人工确认——不阻断流程，但必须让人看见。
"""

import os
import re
import sys
import yaml
from openai import OpenAI
from typing import List, Optional

from utils import resolve_llm_config, clean_llm_response

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


# 格式规范文件的默认位置（相对项目根目录）
DEFAULT_SPEC_PATH = os.path.join('data', 'linkedin-post-format.md')


class LinkedInWriter:
    """领英动态文案生成器"""

    def __init__(self, config_path: str = None, llm_name: str = None,
                 model_name: str = None, silent: bool = False):
        """
        参数:
            config_path: 配置文件路径，默认为项目根目录的 config.yaml
            llm_name:    LLM 提供商名称（如 qwen / deepseek），不传则用 default
            model_name:  模型名覆盖（不传则用 config.yaml 中的默认值）
            silent:      安静模式，不打印初始化横幅
        """
        if config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            config_path = os.path.join(project_root, "config.yaml")

        self.project_root = os.path.dirname(os.path.abspath(config_path))

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        provider = resolve_llm_config(self.config, llm_name)
        self.model = model_name or provider['model_name']
        self.provider_name = provider.get('name', 'unknown')

        self.client = OpenAI(
            api_key=provider['api_key'],
            base_url=provider['base_url'],
        )

        if not silent:
            print(f"✓ 领英文案生成器初始化完成")
            print(f"  - Provider: {self.provider_name}")
            print(f"  - Model: {self.model}")

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(self, blog_path: str, output_dir: str,
                 spec_path: str = None) -> str:
        """
        根据博客文件生成领英动态文案。

        参数:
            blog_path:  博客 Markdown 文件路径（blog_output/*.md）
            output_dir: 输出目录（通常为 article_dir/linkedin/）
            spec_path:  格式规范文件路径，默认为 data/linkedin-post-format.md

        返回:
            生成的文案文件路径

        异常:
            FileNotFoundError: 博客文件或规范文件不存在
            RuntimeError:      LLM 调用失败或返回空内容
        """
        with open(blog_path, 'r', encoding='utf-8') as f:
            blog_content = f.read()

        if spec_path is None:
            spec_path = os.path.join(self.project_root, DEFAULT_SPEC_PATH)
        if not os.path.exists(spec_path):
            raise FileNotFoundError(f"格式规范文件不存在: {spec_path}")

        with open(spec_path, 'r', encoding='utf-8') as f:
            format_spec = f.read()

        blog_url = self._build_blog_url(blog_path)
        print(f"  🤖 正在调用 LLM 生成领英文案...")
        print(f"     博客链接: {blog_url}")

        post = self._call_llm(blog_content, format_spec, blog_url)

        # 数字溯源核对——这是防止编造数值的最后一道关
        self._verify_numbers(post, blog_content)

        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, 'linkedin_post.txt')
        with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(post.rstrip() + '\n')

        return out_path

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_blog_url(blog_path: str) -> str:
        """
        由博客文件名推导线上链接。

        blog_output/ABACUS_2026_09_24.md
            → https://blogs.deepmodeling.com/ABACUS_2026_09_24/
        """
        stem = os.path.splitext(os.path.basename(blog_path))[0]
        return f"https://blogs.deepmodeling.com/{stem}/"

    def _call_llm(self, blog_content: str, format_spec: str,
                  blog_url: str) -> str:
        """调用 LLM 生成文案，返回清理后的纯文本"""
        system_prompt = f"""你是 DeepModeling 社区的内容编辑，为博客文章撰写领英动态文案。

工作方式:
1. 先读完博客全文，再读格式规范
2. 按规范里的「模板选择逻辑」判断这篇文章适合哪个模板（A/B/C/D/E），
   判断依据是文章本身的内容特征，不要为了好看硬套模板
3. 输出纯文本文案，不要用 Markdown 语法（不要 # 标题、不要 ** 加粗）

最高优先级的约束——所有数字必须来自博客原文:
    文案里出现的每一个具体数值（百分比、倍数、eV、atom 数、时间、精度等）
    都必须在博客正文里能找到对应表述。禁止以下行为:
    - 根据已有数字推算新的数字（如由 3.00/2.90 算出"误差 0.1 eV"）
    - 补充文章没提到的指标（如文章只讲了效率，却写"成本降低 50%"）
    - 把范围值改写成具体值，或反之
    如果文章里可用的数字不够撑起 bullet，就减少 bullet 数量，或者改用
    叙事式描述，宁少勿编。编造的数字会被公开发布出去，代价很高。

其他要求:
    - 博客链接固定用: {blog_url}
    - 标签: 必须含 #DeepModeling，以及 #AIforScience / #AI4Science / #AI4S 之一
    - 机构署名: 正文中要出现研究团队所属机构全称（从博客正文里找，不要臆造）
    - 期刊名: 末尾注明，格式 `Published in <期刊>.`
    - 长度: 自然写完即可，不要主动凑字数；明显超过约 1300 字符再精简

输出格式:
    直接输出文案正文，不要任何前言、说明、思考过程或代码块包裹。
    第一行就是文案的第一行。"""

        user_prompt = f"""# 博客全文

{blog_content}

---

# 领英动态格式规范

{format_spec}

---

请生成这篇博客的领英动态文案。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=16000,
            )
        except Exception as e:
            # 不吞掉异常：生成失败必须让上游看见，由上游决定重试还是跳过。
            # 静默回退一个"兜底文案"是最危险的行为——文案会带着编造的
            # 内容一路发到公开平台，而没有任何人察觉生成步骤其实失败了。
            raise RuntimeError(f"领英文案生成失败: {e}") from e

        post = self._extract_content(response)
        return clean_llm_response(post)

    @staticmethod
    def _extract_content(response) -> str:
        """
        取回 LLM 正文并校验非空。

        推理模型的 max_tokens 是思维链与正文的共享预算，额度不足时会返回
        finish_reason='length' 且 content 为空。空内容必须当错误抛出，
        否则空串会被当成"生成成功"写进文件。
        """
        choice = response.choices[0]
        content = choice.message.content or ''
        finish = choice.finish_reason

        if not content.strip():
            hint = ''
            usage = getattr(response, 'usage', None)
            if usage is not None:
                details = getattr(usage, 'completion_tokens_details', None)
                reasoning = getattr(details, 'reasoning_tokens', None)
                if reasoning:
                    hint = f'（思维链占用 {reasoning} tokens；请调大 max_tokens）'
            raise RuntimeError(
                f"领英文案生成: 模型返回空内容 "
                f"[finish_reason={finish}]{hint}"
            )

        if finish == 'length':
            print(f"  ⚠️ 文案输出被 max_tokens 截断，内容可能不完整")

        return content

    @staticmethod
    def _verify_numbers(post: str, blog_content: str) -> List[str]:
        """
        核对文案里的数字是否都能在博客正文中找到出处。

        返回「未找到出处」的数字列表（空列表表示全部对得上）。
        只做提示，不阻断流程——正常引用也可能因为格式差异（如博客写
        `20 times`、文案写 `20×`）被判为未命中，需要人工看一眼。

        排除项:
        - 链接里的数字（博客 URL 自带日期和分类）
        - 年份（出现在机构署名、期刊信息里，属正常引用）
        - 数字 0 和 1（"ML1"、"Figure 1"、"one of" 之类过于普遍，误报率极高）
        """
        post_no_url = re.sub(r'https?://\S+', '', post)
        blog_no_url = re.sub(r'https?://\S+', '', blog_content)

        # 从文案里抽出数字 token（含小数），保持原样比较
        candidates = re.findall(r'\d+(?:\.\d+)?', post_no_url)

        missing = []
        for num in sorted(set(candidates), key=float):
            if num in ('0', '1'):       # 出现频率过高，误报率不可接受
                continue
            if re.fullmatch(r'(19|20)\d{2}', num):   # 年份
                continue
            # 用词边界匹配，避免 "20" 命中 "2026"
            if not re.search(r'(?<![\d.])' + re.escape(num) + r'(?![\d])',
                             blog_no_url):
                missing.append(num)

        if missing:
            print(f"  ⚠️ 以下数字未能在博客正文中找到出处，请人工确认:")
            for num in missing:
                print(f"       {num}")
            print(f"     编造数值是严重问题，确认无误后再发布")
        else:
            print(f"  ✓ 数字溯源核对通过")

        return missing
