"""
微信公众号文章下载 + 自动翻译 + 格式转换 — 全自动流水线
=========================================================
功能:
- 下载微信公众号文章（内容 + 图片）
- LLM 翻译为英文
- 自动转换为 deepmodeling/blog 格式
- 交互模式: 选模型 → 输链接 → 全自动

使用方法:
    python src/main.py                    # 交互模式（推荐）
    python src/main.py --url "..."        # 命令行单篇
    python src/main.py --file urls.txt    # 批量处理
"""

import os
import sys
import argparse
import yaml
from typing import Tuple, List

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from downloader import WeChatDownloader
from translator import Translator
from converter import BlogConverter
from oss_uploader import create_uploader
from github_uploader import create_uploader as create_github_uploader
from linkedin_writer import LinkedInWriter
from decorative_filter import build_hash_library


# ===================================================================
# 工具函数
# ===================================================================

def _ask_retry(step: str, error: str) -> bool:
    """步骤失败时询问用户：重试 还是 继续。返回 True=重试, False=继续"""
    print(f"\n  ❌ [{step}] 失败: {error}")
    while True:
        choice = input("  [1] 重试  [2] 跳过继续: ").strip()
        if choice == '1':
            return True
        elif choice == '2':
            return False
        print("  请输入 1 或 2")


# ===================================================================
# 全自动流水线
# ===================================================================

class WeChatTranslatePipeline:
    """下载 → 翻译 → 格式转换 全自动流水线"""

    def __init__(self, llm_name: str = None, model_name: str = None,
                 silent: bool = False):
        """
        参数:
            llm_name:  LLM 提供商名称（qwen / deepseek）
            model_name: 模型名（覆盖 config.yaml）
            silent:     安静模式（交互模式下少打横幅）
        """
        self.llm_name = llm_name
        self.model_name = model_name

        if not silent:
            print("=" * 60)
            print("📗 微信公众号文章 → 博客格式 全自动流水线")
            print("=" * 60)

        self.downloader = WeChatDownloader()
        self.translator = Translator(llm_name=llm_name, model_name=model_name)

        self.converter = BlogConverter(llm_name=llm_name, model_name=model_name)
        self.oss_uploader = create_uploader()  # None if not configured
        self.github_uploader = create_github_uploader()  # None if not configured
        self.linkedin_writer = LinkedInWriter(
            llm_name=llm_name, model_name=model_name, silent=True
        )

        if not silent:
            print("\n✓ 流水线就绪")
            if self.oss_uploader:
                print(f"  - OSS: {self.oss_uploader.bucket}.{self.oss_uploader.endpoint}")
            if self.github_uploader:
                print(f"  - GitHub: {self.github_uploader.repo}")
            print("=" * 60)

    def process(self, url: str) -> str:
        """
        全自动处理: 下载 → 翻译 → 分类 → OSS上传 → 格式转换
        任一步骤失败都会询问用户重试或继续。

        返回: 博客输出文件路径，失败返回 None
        """
        from datetime import date

        print(f"\n{'─' * 60}")
        print(f"🎯 {url[:60]}...")
        print(f"{'─' * 60}")

        # ── Step 1: 下载 ──
        print("\n[Step 1/7] 下载文章...")
        while True:
            result = self.downloader.download(url)
            if result and result[0]:
                break
            if not _ask_retry("下载", "文章下载失败"):
                return None

        zh_markdown, article_dir, image_map, title = result
        original_title = title   # 文件名基准，不随 Step 2 的改标题而变
        print(f"   ✓ 标题: {title}")
        print(f"   ✓ 图片: {len(image_map)} 张")

        # ── 翻译确认断点 ──
        from utils import find_file_by_suffix
        zh_md_path = find_file_by_suffix(article_dir, '_zh.md')

        print(f"\n[Step 2/7] 翻译")
        print(f"   中文原文: {zh_md_path}")
        print(f"   ── 这一步可以改什么 ──")
        print(f"     • 中文标题 / 正文有问题（段落串行、公式乱、缺段）:")
        print(f"       直接编辑上面这个 _zh.md，保存后按 1 —— 检测到改动就用改后的版本翻译")
        print(f"     • 图片不归这一步管，留到 Step 4 再调")
        print(f"     • 什么都不改: 直接按 1")
        while True:
            choice = input("   是否调用 LLM 翻译？[1] 确认翻译  [2] 跳过: ").strip()
            if choice == '1':
                break
            if choice == '2':
                print("   ⏭️ 已跳过翻译，流程结束")
                print(f"   📁 中文版本已保存: {article_dir}")
                return article_dir
            print("   请输入 1 或 2")

        # 用户在断点处可能改过 _zh.md；改了就用改后的内容，没改则维持原样
        if zh_md_path:
            edited = self._read_edited_zh(zh_md_path, title, zh_markdown)
            if edited is not None:
                title, zh_markdown = edited
                print(f"   ✏️ 检测到 _zh.md 已被修改，改用改后的中文原文")
                print(f"      标题: {title}")

        # ── Step 2: 翻译 + 审核 ──
        print(f"   翻译中 ({self.translator.provider_name}/{self.translator.model})...")
        while True:
            try:
                en_markdown, review_result = self.translator.translate_with_review(
                    zh_markdown, title, auto_fix=True
                )
                score = review_result.get('score', 0)
                passed = review_result.get('passed', False)
                status = '✅' if passed else '⚠️'
                print(f"   ✓ 分数: {score}/100 {status}")
                break
            except Exception as e:
                if not _ask_retry("翻译", str(e)):
                    return None

        # ── Step 3: 保存 ──
        print("\n[Step 3/7] 保存文件...")
        # 文件名用原标题：Step 2 若改过中文标题，_en.md 仍与 _zh.md、
        # images_map.txt 保持同一套文件名，避免同一次运行产出两套名字。
        en_md_path = self._save_en_version(
            zh_markdown, en_markdown, original_title, url, article_dir,
            image_map, review_result
        )

        # ── Step 4: 分类 → OSS 上传 ──
        # 用中文原文分类；先去掉元数据块（> 来源, > ⚠️, ---），避免干扰 LLM
        import re as _re
        _zh_body = _re.sub(
            r'^# .+\n+|^> .+\n+|^---\s*\n', '', zh_markdown, flags=_re.MULTILINE
        ).strip()
        while True:
            try:
                category = self.converter.classify_category(title, _zh_body)
                print(f"   🏷 分类: {category}")
                break
            except Exception as e:
                if not _ask_retry("分类", str(e)):
                    category = "Other"
                    print(f"   🏷 回退分类: {category}")
                    break

        if self.oss_uploader:
            post_date = date.today().isoformat()
            oss_folder = self.converter.make_oss_folder(category, post_date)

            # 统计可上传图片
            images_dir = os.path.join(article_dir, 'images')
            uploadable = 0
            if os.path.isdir(images_dir):
                from utils import IMAGE_EXTENSIONS
                uploadable = sum(
                    1 for f in os.listdir(images_dir)
                    if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
                )

            print(f"\n[Step 4/7] 上传图片到 OSS")
            print(f"   目标: {self.oss_uploader.bucket}.{self.oss_uploader.endpoint}")
            print(f"   文件夹: {oss_folder}")
            print(f"   图片: {uploadable} 张")
            print(f"   ── 这一步可以改什么 ──")
            print(f"     【改英文标题 / 正文】")
            print(f"       编辑: {en_md_path}")
            print(f"       第 1 行 # 后面就是最终标题，正文随意改 —— Step 5 直接用这个文件，改了就生效")
            print(f"     【删掉多余的图】封面图/装饰图没被自动过滤掉时:")
            print(f"       把图片文件移进 {images_dir}\\_filtered\\")
            print(f"       → 只移文件即可，Step 5 会自动删掉正文里对应引用，不用手改任何文本")
            print(f"     【替换某张图】用同名文件覆盖 {images_dir}\\ 里的原图")
            print(f"     【什么都不改】直接按 1 继续")
            print(f"   ⚠️ 别手改 images_map.txt（图片路径表），它由程序维护；")
            print(f"      图片增删一律用「移文件」的方式，避免正文引用和实际文件对不上。")
            print(f"   ℹ️ 图片一旦传到 OSS 不便撤回，所以确认放在这一步；")
            print(f"      文字的修改不着急，Step 5 之前任何时候都还来得及。")

            while True:
                choice = input("   [1] 确认上传  [2] 跳过: ").strip()
                if choice == '1':
                    while True:
                        try:
                            self.oss_uploader.upload_and_update_map(
                                article_dir, image_map, oss_folder
                            )
                            break
                        except Exception as e:
                            if not _ask_retry("OSS 上传", str(e)):
                                print("   ⚠️ 跳过 OSS 上传，使用原始 URL")
                                break
                    break
                elif choice == '2':
                    print("   ⏭️ 已跳过 OSS 上传（使用原始 URL）")
                    break
                else:
                    print("   请输入 1 或 2")
        else:
            print(f"\n[Step 4/7] OSS 未配置，跳过上传")

        # ── Step 5: 格式转换 ──
        print(f"\n[Step 5/7] 格式转换 → 博客格式...")
        blog_path = self.converter.convert_article(
            article_dir=article_dir,
            output_dir=os.path.join(article_dir, 'blog_output'),
            category=category,
        )

        # ── Step 6: 上传 GitHub ──
        if self.github_uploader:
            blog_basename = os.path.basename(blog_path)
            print(f"\n[Step 6/7] 上传 GitHub → PR")
            print(f"   前 5 步已完成，即将提交到 {self.github_uploader.repo}")
            print(f"   文件: {blog_basename}")
            print(f"   ── 这一步可以改什么 ──")
            print(f"     【最后检查一遍】即将提交的文件:")
            print(f"       {blog_path}")
            print(f"       改它就等于改 PR 内容 —— 上传用的就是这个文件，改完按 1 即可")
            print(f"       重点看: frontmatter 的 title / categories、图片链接是否为 OSS 地址")
            print(f"     【什么都不改】直接按 1")

            while True:
                choice = input("   [1] 提交 PR  [2] 跳过: ").strip()
                if choice == '1':
                    while True:
                        try:
                            pr_url = self.github_uploader.upload_post(blog_path, article_dir)
                            if pr_url:
                                print(f"   ✅ PR: {pr_url}")
                            break
                        except Exception as e:
                            if not _ask_retry("GitHub 上传", str(e)):
                                print("   ⚠️ 上传失败，已跳过")
                                break
                    break
                elif choice == '2':
                    print(f"   ⏭️ 已跳过 GitHub 上传（blog_output 文件已生成，可稍后手动上传）")
                    break
                else:
                    print("   请输入 1 或 2")
        else:
            print(f"\n[Step 6/7] GitHub 未配置或 gh 不可用，跳过上传")

        # ── Step 7: 生成领英文案 ──
        linkedin_dir = os.path.join(article_dir, 'linkedin')
        print(f"\n[Step 7/7] 生成领英动态文案")
        print(f"   基于博客文件生成，输出到: {linkedin_dir}")
        print(f"   ── 这一步可以改什么 ──")
        print(f"     【生成后】文案是纯文本，直接全选复制即可发领英")
        print(f"     【不满意】改完博客正文后重跑这一步，或手动编辑输出的 txt")
        print(f"   ⚠️ 文案里的数字会自动核对是否出自博客正文，")
        print(f"      出现「未能找到出处」提示时务必人工确认再发布")

        while True:
            choice = input("   [1] 生成文案  [2] 跳过: ").strip()
            if choice == '1':
                while True:
                    try:
                        linkedin_path = self.linkedin_writer.generate(
                            blog_path=blog_path,
                            output_dir=linkedin_dir,
                        )
                        print(f"   ✅ 文案: {linkedin_path}")
                        print(f"\n{'·' * 60}")
                        with open(linkedin_path, 'r', encoding='utf-8') as f:
                            print(f.read().rstrip())
                        print(f"{'·' * 60}")
                        break
                    except Exception as e:
                        if not _ask_retry("领英文案生成", str(e)):
                            print("   ⚠️ 跳过领英文案生成")
                            break
                break
            elif choice == '2':
                print(f"   ⏭️ 已跳过领英文案生成")
                break
            else:
                print("   请输入 1 或 2")

        # ── 完成 ──
        print(f"\n{'─' * 60}")
        print(f"✅ 完成!")
        print(f"   📁 {article_dir}")
        print(f"   📄 博客文件: {os.path.basename(blog_path)}")
        print(f"{'─' * 60}")

        return blog_path

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _read_edited_zh(self, zh_md_path, title, zh_markdown):
        """
        检测用户在 Step 2 断点处是否改过 _zh.md。

        下载时该文件写死为 "# {title}\\n\\n{body}"，把 (title, body) 复原成
        同样的字符串与磁盘内容比对即可判断有没有被编辑——不需要哈希或时间戳，
        也避免依赖文件 mtime（编辑器保存后 mtime 必然变化，无法区分内容是否真变）。

        返回 (new_title, new_body)；未改动、读取失败或改空则返回 None。
        """
        try:
            with open(zh_md_path, 'r', encoding='utf-8') as f:
                current = f.read()
        except OSError:
            return None

        if current.strip() == f"# {title}\n\n{zh_markdown}".strip():
            return None  # 原样未动

        lines = current.split('\n')
        new_title, body_start = '', 0
        for i, line in enumerate(lines):
            if line.strip().startswith('# '):
                new_title = line.strip()[2:].strip()
                body_start = i + 1
                break

        body = '\n'.join(lines[body_start:]).strip()
        if not body:
            print("   ⚠️ _zh.md 内容为空，忽略改动，沿用原中文原文")
            return None

        return (new_title or title), body

    def _save_en_version(self, zh_content, en_content, title, url,
                         article_dir, image_map, review_result=None):
        """保存英文翻译"""
        import re
        safe_title = "".join(c for c in title if c not in r'/:*?"<>|').strip()[:80]

        # 只把「开头那一行 H1」当作文章标题取走。正文里的小节标题已在
        # 抓取阶段降级为 ##，所以正常情况下开头这个 # 就是译文标题。
        # 不能用 re.MULTILINE 全文搜索后无条件删除：若模型没输出标题行，
        # 那样会把正文第一个小节标题误当标题吃掉（第一节标题凭空消失）。
        en_title_match = re.match(r'^#\s+(.+?)\s*$', en_content.lstrip(), re.MULTILINE)
        if en_title_match:
            en_title = en_title_match.group(1).strip()
            en_content = re.sub(r'^\s*#\s+.+\n+', '', en_content, count=1)
            # 如果 LLM 输出的标题仍是中文，提示用户
            if re.search(r'[一-鿿]', en_title):
                print(f"   ⚠️ 标题可能未翻译（含中文）: {en_title[:60]}")
        else:
            en_title = title
            print(f"   ⚠️ LLM 输出缺少 # 标题行，回退到中文原标题")

        en_md_path = os.path.join(article_dir, f"{safe_title}_en.md")

        with open(en_md_path, 'w', encoding='utf-8') as f:
            f.write(f"# {en_title}\n\n")
            f.write(f"> Source: {url}\n")
            f.write(f"> Original title: {title}\n")
            f.write(f"> Translated by {self.translator.provider_name}\n")
            if review_result:
                score = review_result.get('score', 0)
                passed = review_result.get('passed', False)
                f.write(f"> Quality score: {score}/100"
                        f" ({'PASSED' if passed else 'NEEDS REVIEW'})\n")
            f.write("\n---\n\n")
            f.write(en_content)

        if review_result and review_result.get('issues'):
            report_path = os.path.join(article_dir, f"{safe_title}_review.md")
            self._save_review_report(report_path, review_result, title)

        return en_md_path

    def _save_review_report(self, report_path, review_result, title):
        """保存审核报告"""
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# Translation Review Report\n\n")
            f.write(f"**Article**: {title}\n\n")
            score = review_result.get('score', 0)
            passed = review_result.get('passed', False)
            f.write(f"## Summary\n\n")
            f.write(f"- **Score**: {score}/100\n")
            f.write(f"- **Status**: {'PASSED' if passed else 'NEEDS REVIEW'}\n\n")
            for i, issue in enumerate(review_result.get('issues', []), 1):
                f.write(f"### {i}. {issue.get('type', 'unknown').upper()}\n")
                f.write(f"- **Location**: {issue.get('location', 'N/A')}\n")
                f.write(f"- **Description**: {issue.get('description', '')}\n\n")
            for s in review_result.get('suggestions', []):
                f.write(f"- {s}\n")

    def batch_process(self, urls: list) -> dict:
        """批量处理"""
        results = {}
        print(f"\n📚 批量处理: {len(urls)} 篇")
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{len(urls)}]")
            try:
                blog_path = self.process(url)
                results[url] = {'status': 'success', 'blog_path': blog_path}
            except Exception as e:
                print(f"❌ 失败: {e}")
                results[url] = {'status': 'failed', 'error': str(e)}

        success = sum(1 for r in results.values() if r['status'] == 'success')
        print(f"\n{'=' * 60}")
        print(f"📊 完成: {success}/{len(urls)} 篇")
        print(f"{'=' * 60}")
        return results


# ===================================================================
# 交互模式
# ===================================================================

# 各提供商的已知模型列表（用于提示和校验）
KNOWN_MODELS = {
    "qwen": ["qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash",
             "qwen-max"],   # qwen-max 是旧版别名，保留向后兼容
    "deepseek": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-v4.1",
                 "deepseek-chat", "deepseek-reasoner"],
}


def _load_providers(config_path: str = None) -> dict:
    """加载 LLM 提供商列表"""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    return cfg.get('llm', {}).get('providers', {})


def _pick_llm(providers: dict) -> Tuple[str, str]:
    """
    交互式选择 LLM 提供商和模型（全程数字键）。

    返回: (provider_name, model_name)
    """
    names = list(providers.keys())

    # ── Step 1: 选提供商 ──
    print("\n可用 LLM 提供商:")
    for i, name in enumerate(names, 1):
        model = providers[name].get('model_name', '?')
        print(f"  [{i}] {name:<12} 当前默认: {model}")
    print(f"  [Enter] 退出")

    while True:
        choice = input("\n选择 LLM: ").strip()
        if choice == '':
            return None, None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                break
        except ValueError:
            pass
        print(f"  输入 1-{len(names)} 或回车退出")

    provider = names[idx]
    default_model = providers[provider].get('model_name', '')

    # ── Step 2: 选具体模型 ──
    alternatives = KNOWN_MODELS.get(provider, [])
    # 构建去重列表，默认模型排第一
    seen = {default_model}
    models = [default_model] if default_model else []
    for m in alternatives:
        if m not in seen:
            models.append(m)
            seen.add(m)

    if len(models) == 1:
        print(f"\n模型: {models[0]} (唯一)")
        return provider, models[0]

    print(f"\n{provider} 可用模型:")
    for i, m in enumerate(models, 1):
        tag = " ★默认" if m == default_model else ""
        print(f"  [{i}] {m}{tag}")
    print(f"  [Enter] 使用默认 ({default_model})")

    while True:
        choice = input("模型: ").strip()
        if choice == '':
            return provider, default_model
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model = models[idx]
                print(f"\n✓ {provider} / {model}")
                return provider, model
        except ValueError:
            pass
        print(f"  输入 1-{len(models)} 或回车")


def interactive_mode():
    """交互模式"""
    print("=" * 60)
    print("📗 微信公众号文章 → 博客格式 全自动流水线")
    print("=" * 60)

    # 加载配置
    providers = _load_providers()
    if not providers:
        print("❌ config.yaml 中未配置 LLM，请先配置后重试")
        return

    # 选模型（一次，后面复用）
    provider, model = _pick_llm(providers)
    if provider is None:
        print("已退出 👋")
        return

    # 初始化流水线
    print("\n⏳ 初始化...")
    pipeline = WeChatTranslatePipeline(
        llm_name=provider, model_name=model, silent=True
    )

    # 哈希库更新提示（进文章循环前问一次）
    print(f"\n{'─' * 60}")
    print("🧹 装饰图过滤")
    update = input("是否更新装饰图哈希库？[1] 更新  [Enter] 跳过: ").strip()
    if update == '1':
        count = build_hash_library()
        if count == 0:
            print("   💡 提示: 将装饰图放入 data/decorative_samples/ 后重新运行 --build")
        else:
            # 重建后重载过滤器内存数据
            pipeline.downloader.decorative_filter._load()
    print(f"{'─' * 60}")

    # 主循环：输入链接 → 全自动处理
    while True:
        print(f"\n{'─' * 60}")
        url = input("微信文章链接 [回车退出]: ").strip()

        if not url:
            print("已退出 👋")
            break

        try:
            pipeline.process(url)
        except Exception as e:
            print(f"\n❌ 失败: {e}")


# ===================================================================
# 命令行入口
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description='微信公众号文章下载 + 翻译 + 格式转换'
    )
    parser.add_argument('--url', '-u', type=str, help='微信文章链接')
    parser.add_argument('--file', '-f', type=str, help='URL 列表文件（批量）')
    parser.add_argument('--download-only', action='store_true', help='仅下载')
    parser.add_argument('--no-convert', action='store_true', help='跳过格式转换')
    parser.add_argument('--llm', default=None, help='LLM 提供商')
    parser.add_argument('--model', default=None, help='覆盖模型名')
    args = parser.parse_args()

    # 命令行：单篇
    if args.url:
        pipeline = WeChatTranslatePipeline(
            llm_name=args.llm, model_name=args.model
        )
        if args.download_only:
            result = pipeline.downloader.download(args.url)
            if result and pipeline.oss_uploader:
                from datetime import date
                _, article_dir, image_map, _ = result
                # 仅下载模式下无法分类，用时间戳占位
                ts = date.today().strftime('%d_%m_%Y')
                pipeline.oss_uploader.upload_and_update_map(article_dir, image_map, f"Download_{ts}")
        else:
            pipeline.process(args.url)
        return

    # 命令行：批量
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            urls = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        pipeline = WeChatTranslatePipeline(
            llm_name=args.llm, model_name=args.model
        )
        pipeline.batch_process(urls)
        return

    # 默认：交互模式
    interactive_mode()


if __name__ == "__main__":
    main()
