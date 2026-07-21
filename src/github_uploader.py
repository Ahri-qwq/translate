"""
GitHub 博客文章上传模块
=======================
使用 gh CLI 将翻译完成的博客文章通过 PR 上传到 deepmodeling/blog。

设计原则:
- 零额外依赖：直接调用 gh CLI + git 命令，不引入 PyGithub 等第三方库
- 仓库隔离：目标仓库 clone 到项目外部的缓存目录，互不污染
- PR 工作流：创建分支 → 推送 → 提 PR，绝不直接 push master
- 容错：gh 未安装/未登录时返回 None，流水线安全跳过
- 幂等：重复运行同一文章时自动覆盖旧分支和 PR

前置条件: 已安装 GitHub CLI 并登录
  安装: winget install GitHub.cli
  登录: gh auth login
"""

import glob
import os
import re
import subprocess
import sys
from typing import Dict, Optional

from utils import find_file_by_suffix

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


class GitHubUploader:
    """GitHub 博客上传器 —— 封装 gh CLI + git 命令"""

    def __init__(self, config: dict):
        """
        参数:
            config: GitHub 配置字典，需包含:
                repo: 目标仓库 (如 "deepmodeling/blog")
                branch: 目标分支 (默认 "master")
                cache_dir: 本地缓存目录 (留空则默认 ../blog-cache)
        """
        self.repo = config['repo']
        self.branch = config.get('branch', 'master')

        # 缓存目录：默认在项目外部 (../blog-cache)
        cache_dir = config.get('cache_dir', '')
        if cache_dir:
            self.cache_dir = os.path.abspath(os.path.expanduser(cache_dir))
        else:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.cache_dir = os.path.normpath(os.path.join(project_root, '..', 'blog-cache'))

        self._gh_exe = None       # 延迟查找，允许实例化后检测
        self._repo_dir = os.path.join(self.cache_dir, self.repo.split('/')[-1])

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _run(cmd: list, cwd: str = None, timeout: int = 30,
             capture_output: bool = True, text: bool = True,
             encoding: str = 'utf-8', errors: str = 'replace',
             **kwargs):
        """运行命令，统一处理 Windows 编码问题。返回 CompletedProcess。"""
        if cwd:
            kwargs['cwd'] = cwd
        try:
            return subprocess.run(
                cmd, capture_output=capture_output, text=text,
                timeout=timeout, encoding=encoding, errors=errors,
                **kwargs,
            )
        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """检查 gh CLI 是否可用且已登录。成功返回 True。"""
        if self._gh_exe is None:
            try:
                self._gh_exe = self._find_gh()
            except RuntimeError:
                return False

        # 检查登录状态
        try:
            result = self._run(
                [self._gh_exe, 'auth', 'status'],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def upload_post(self, md_file: str, article_dir: str = None) -> Optional[str]:
        """
        上传单篇博客文章，创建 PR。

        参数:
            md_file:     博客 .md 文件路径 (blog_output/{CATEGORY}_{YYYY}_{MM}_{DD}.md)
            article_dir: 文章输出目录，用于提取 _en.md 中的元数据（可选）

        返回:
            PR URL 字符串，失败返回 None
        """
        # 确保 gh 可用
        if not self.is_configured():
            print("  ❌ gh CLI 未安装或未登录。请先运行: gh auth login")
            return None

        if not os.path.isfile(md_file):
            print(f"  ❌ 文件不存在: {md_file}")
            return None

        # 从文件名提取分支名
        basename = os.path.splitext(os.path.basename(md_file))[0]  # e.g. ABACUS_2026_07_15
        branch_name = f"post-{basename}"

        # 提取元数据用于 PR body
        if article_dir is None:
            # 从 md_file 反推: blog_output/file.md → 上级目录 = article_dir
            article_dir = os.path.dirname(os.path.dirname(os.path.abspath(md_file)))
        metadata = self._extract_metadata(article_dir, md_file)

        print(f"\n  📤 上传博客到 GitHub...")
        print(f"     仓库: {self.repo}")
        print(f"     分支: {branch_name}")
        print(f"     缓存: {self._repo_dir}")

        # Step 1: 确保本地仓库最新
        if not self._ensure_repo():
            return None

        # Step 2: 同步 master
        if not self._sync_master():
            return None

        # Step 3: 创建/重置分支
        if not self._prepare_branch(branch_name):
            return None

        # Step 4: 复制博客文件到 source/_posts/
        posts_dir = os.path.join(self._repo_dir, 'source', '_posts')
        os.makedirs(posts_dir, exist_ok=True)
        dest = os.path.join(posts_dir, os.path.basename(md_file))

        import shutil
        shutil.copy2(md_file, dest)
        print(f"     ✓ 已复制: {os.path.basename(md_file)} → source/_posts/")

        # Step 5: 提交
        if not self._commit(branch_name, basename):
            return None

        # Step 6: 推送
        if not self._push(branch_name):
            return None

        # Step 7: 创建 PR
        pr_url = self._create_pr(branch_name, basename, metadata)

        return pr_url

    # ------------------------------------------------------------------
    # 内部方法 — 仓库管理
    # ------------------------------------------------------------------

    def _ensure_repo(self) -> bool:
        """确保本地缓存仓库存在。不存在则 clone，存在则验证。"""
        if os.path.isdir(os.path.join(self._repo_dir, '.git')):
            return True  # 已存在

        print(f"     ⏳ 首次使用，正在 clone {self.repo} ...")
        os.makedirs(self.cache_dir, exist_ok=True)

        clone_url = f"https://github.com/{self.repo}.git"
        try:
            # core.protectNTFS=false: 允许文件名含 : 等 Windows 非法字符
            # (远程仓库存在此类历史文件，我们只添加新文件，不受影响)
            result = self._run(
                ['git', 'clone', '-c', 'core.protectNTFS=false',
                 clone_url, self._repo_dir],
                timeout=300,
            )
            if result is None:
                print(f"     ❌ clone 超时（>5分钟），请检查网络")
                return False
            if result.returncode == 0:
                print(f"     ✓ clone 完成")
                return True
            else:
                err = result.stderr.strip() if result.stderr else '未知错误'
                print(f"     ❌ clone 失败: {err}")
                return False
        except Exception as e:
            print(f"     ❌ clone 失败: {e}")
            return False

    def _sync_master(self) -> bool:
        """同步 master 分支到上游最新。"""
        try:
            # 先 fetch，避免未 commit 的本地改动干扰 checkout
            self._run(
                ['git', 'fetch', 'origin', self.branch],
                capture_output=True, text=True, timeout=30,
                cwd=self._repo_dir,
            )

            # 放弃本地未提交的改动，强制切换到干净的 master
            self._run(
                ['git', 'checkout', '--force', self.branch],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )

            # 重置到上游最新
            self._run(
                ['git', 'reset', '--hard', f'origin/{self.branch}'],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )
            return True
        except Exception as e:
            print(f"     ❌ 同步失败: {e}")
            return False

    def _prepare_branch(self, branch_name: str) -> bool:
        """创建新分支（如果已存在则先删除再重建）。"""
        try:
            # 先切回 master（确保不在目标分支上）
            self._run(
                ['git', 'checkout', '--force', self.branch],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )

            # 删除本地分支（如果存在）
            self._run(
                ['git', 'branch', '-D', branch_name],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )

            # 创建新分支
            result = self._run(
                ['git', 'checkout', '-b', branch_name],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )
            if result.returncode == 0:
                print(f"     ✓ 已创建分支: {branch_name}")
                return True
            else:
                print(f"     ❌ 创建分支失败: {result.stderr.strip()}")
                return False
        except Exception as e:
            print(f"     ❌ 准备分支失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 内部方法 — 提交 / 推送 / PR
    # ------------------------------------------------------------------

    def _commit(self, branch_name: str, display_name: str) -> bool:
        """提交变更。"""
        commit_msg = f"上传{display_name}"

        try:
            # git add
            self._run(
                ['git', 'add', 'source/_posts/'],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )

            # git commit（可能没有变更，允许失败但不阻塞）
            result = self._run(
                ['git', 'commit', '-m', commit_msg],
                capture_output=True, text=True, timeout=10,
                cwd=self._repo_dir,
            )

            if result.returncode == 0:
                print(f"     ✓ 已提交: 上传{display_name}")
            else:
                stderr = result.stderr.strip()
                if 'nothing to commit' in stderr:
                    print(f"     ⚠️ 无变更需要提交（文件可能已存在且相同）")
                else:
                    print(f"     ⚠️ 提交警告: {stderr}")
                    # 不阻塞：某些警告不影响后续 push
            return True
        except Exception as e:
            print(f"     ❌ 提交失败: {e}")
            return False

    def _push(self, branch_name: str) -> bool:
        """推送分支到远程。"""
        try:
            result = self._run(
                ['git', 'push', 'origin', branch_name, '--force'],
                capture_output=True, text=True, timeout=60,
                cwd=self._repo_dir,
            )
            if result.returncode == 0:
                print(f"     ✓ 已推送到 origin/{branch_name}")
                return True
            else:
                err = result.stderr.strip()
                print(f"     ❌ 推送失败: {err}")
                return False
        except subprocess.TimeoutExpired:
            print(f"     ❌ 推送超时")
            return False
        except Exception as e:
            print(f"     ❌ 推送失败: {e}")
            return False

    def _create_pr(self, branch_name: str, display_name: str,
                   metadata: dict) -> Optional[str]:
        """通过 gh CLI 创建 Pull Request。"""
        title = f"上传{display_name}"
        body = self._build_pr_body(metadata)

        try:
            result = self._run(
                [
                    self._gh_exe, 'pr', 'create',
                    '--base', self.branch,
                    '--head', branch_name,
                    '--title', title,
                    '--body', body,
                ],
                capture_output=True, text=True, timeout=30,
                cwd=self._repo_dir,
            )

            if result.returncode == 0:
                pr_url = result.stdout.strip()
                print(f"     ✅ PR 已创建: {pr_url}")
                return pr_url
            else:
                stderr = result.stderr.strip()
                # 检测常见错误
                if 'already exists' in stderr.lower():
                    print(f"     ⚠️ PR 已存在（同分支），force push 已自动更新")
                    # 尝试从已有输出中提取 PR URL
                    return self._find_existing_pr(branch_name)
                elif 'No commits between' in stderr:
                    print(f"     ⚠️ 分支与 master 无差异，无需 PR")
                    return None
                else:
                    print(f"     ❌ 创建 PR 失败: {stderr}")
                    return None
        except subprocess.TimeoutExpired:
            print(f"     ❌ 创建 PR 超时")
            return None
        except Exception as e:
            print(f"     ❌ 创建 PR 失败: {e}")
            return None

    def _find_existing_pr(self, branch_name: str) -> Optional[str]:
        """查找已有 PR 的 URL。"""
        try:
            result = self._run(
                [self._gh_exe, 'pr', 'list',
                 '--head', branch_name,
                 '--state', 'open',
                 '--json', 'url',
                 '--jq', '.[0].url'],
                capture_output=True, text=True, timeout=15,
                cwd=self._repo_dir,
            )
            url = result.stdout.strip()
            if url:
                print(f"     ℹ️ 已有 PR: {url}")
                return url
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 内部方法 — 元数据提取
    # ------------------------------------------------------------------

    def _extract_metadata(self, article_dir: str, md_file: str) -> dict:
        """
        从文章目录提取元数据用于 PR body。

        搜索顺序:
        1. _en.md 元数据头（Source, Original title, Translated by, Quality score）
        2. 博客 .md 的 YAML frontmatter（title, categories, date）
        """
        meta = {
            'title_en': '',
            'title_zh': '',
            'source_url': '',
            'translator': '',
            'score': '',
            'categories': [],
            'date': '',
        }

        # ── 从 _en.md 提取 ──
        en_md = self._find_en_md(article_dir)
        if en_md:
            with open(en_md, 'r', encoding='utf-8') as f:
                content = f.read()

            # > Source: URL
            m = re.search(r'>\s*Source:\s*(https?://\S+)', content)
            if m:
                meta['source_url'] = m.group(1)

            # > Original title: ...
            m = re.search(r'>\s*Original title:\s*(.+)', content)
            if m:
                meta['title_zh'] = m.group(1).strip()

            # > Translated by ...
            m = re.search(r'>\s*Translated by\s+(\S+)', content)
            if m:
                meta['translator'] = m.group(1)

            # > Quality score: 95/100 (PASSED)
            m = re.search(r'>\s*Quality score:\s*(\S+)', content)
            if m:
                meta['score'] = m.group(1)

            # # English Title (first heading)
            m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if m and not re.search(r'[一-鿿]', m.group(1)):
                meta['title_en'] = m.group(1).strip()

        # ── 从博客 .md frontmatter 提取 ──
        with open(md_file, 'r', encoding='utf-8') as f:
            blog_content = f.read()

        # YAML frontmatter between ---
        m = re.match(r'^---\s*\n(.*?)\n---', blog_content, re.DOTALL)
        if m:
            frontmatter = m.group(1)
            # title
            t = re.search(r"title:\s*['\"]?(.+?)['\"]?\s*$", frontmatter, re.MULTILINE)
            if t:
                meta['title_en'] = meta['title_en'] or t.group(1).strip()
            # date
            d = re.search(r"date:\s*(\S+)", frontmatter)
            if d:
                meta['date'] = d.group(1).strip()
            # categories as list
            cats = re.findall(r"^\s*-\s*(.+)$", frontmatter, re.MULTILINE)
            if cats:
                meta['categories'] = [c.strip() for c in cats]

        return meta

    @staticmethod
    def _find_en_md(article_dir: str) -> Optional[str]:
        """在文章目录中查找 _en.md 文件（委托 utils.find_file_by_suffix）。"""
        return find_file_by_suffix(article_dir, '_en.md')

    def _build_pr_body(self, meta: dict) -> str:
        """根据元数据构建 PR body。"""
        lines = []

        if meta['title_zh']:
            lines.append(f"**Original**: {meta['title_zh']}")
        if meta['title_en']:
            lines.append(f"**Title**: {meta['title_en']}")
        if meta['source_url']:
            lines.append(f"**Source**: {meta['source_url']}")
        if meta['categories']:
            lines.append(f"**Category**: {', '.join(meta['categories'])}")

        translator_info = meta['translator']
        if meta['score']:
            translator_info += f" · Score: {meta['score']}"
        if translator_info:
            lines.append(f"**Translation**: {translator_info}")

        if lines:
            lines.append("")

        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # 内部方法 — gh CLI 查找
    # ------------------------------------------------------------------

    def _find_gh(self) -> str:
        """查找 gh 可执行文件，返回完整路径。

        搜索顺序: 1) PATH 中的 gh  2) 常见安装目录
        """
        # 1) 先尝试 PATH
        r = self._run(['gh', 'version'], timeout=5)
        if r is not None and r.returncode == 0:
            return 'gh'  # PATH 中可用，直接用命令名

        # 2) 搜索常见安装目录
        if sys.platform == 'win32':
            search_dirs = [
                os.path.expanduser(r'~\AppData\Local\Programs\GitHub CLI\gh.exe'),
                os.path.expanduser(r'~\AppData\Local\GitHub CLI\gh.exe'),
                r'C:\Program Files\GitHub CLI\gh.exe',
                r'C:\Program Files (x86)\GitHub CLI\gh.exe',
            ]
            for path in search_dirs:
                if os.path.isfile(path):
                    return path

        raise RuntimeError(
            "未找到 gh 命令。请先安装 GitHub CLI:\n"
            "  winget install GitHub.cli\n"
            "或访问: https://cli.github.com/"
        )


# ===================================================================
# 工厂函数：从 config.yaml 构建上传器
# ===================================================================

def create_uploader(config_path: str = None) -> Optional[GitHubUploader]:
    """
    从 config.yaml 读取 GitHub 配置，创建 GitHubUploader 实例。

    如果未配置 github 段或 gh 不可用，返回 None（流水线安全跳过）。
    """
    import yaml

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config.yaml',
        )

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    github_cfg = cfg.get('github', {})
    if not github_cfg:
        return None

    repo = github_cfg.get('repo', '')
    if not repo:
        return None

    uploader = GitHubUploader(github_cfg)

    # 检查 gh 是否可用
    try:
        if not uploader.is_configured():
            print("  ⚠️ gh CLI 未安装或未登录，GitHub 上传将跳过")
            return None
    except Exception:
        return None

    return uploader


# ===================================================================
# 命令行入口（独立测试用）
# ===================================================================

def main():
    """独立测试 GitHub 上传功能"""
    import argparse

    parser = argparse.ArgumentParser(
        description='GitHub 博客上传工具 — 通过 PR 上传到 deepmodeling/blog'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--file', help='单个博客 .md 文件路径')
    group.add_argument('--dir', help='文章输出目录（自动找 blog_output/ 和 _en.md）')
    parser.add_argument('--config', default=None, help='config.yaml 路径')
    args = parser.parse_args()

    uploader = create_uploader(args.config)
    if uploader is None:
        print("❌ GitHub 上传未配置或 gh 不可用")
        print("   请先安装 gh CLI: winget install GitHub.cli")
        print("   然后登录: gh auth login")
        print("   并确保 config.yaml 中有 github 配置段")
        return

    if args.file:
        md_file = args.file
        article_dir = None
    else:
        # --dir: 找 blog_output 下的 .md 文件
        blog_dir = os.path.join(args.dir, 'blog_output')
        if not os.path.isdir(blog_dir):
            print(f"❌ 未找到 blog_output 目录: {blog_dir}")
            return
        md_files = [f for f in os.listdir(blog_dir) if f.endswith('.md')]
        if not md_files:
            print(f"❌ blog_output 中无 .md 文件")
            return
        md_file = os.path.join(blog_dir, md_files[0])
        article_dir = args.dir

    print(f"文件: {md_file}")
    pr_url = uploader.upload_post(md_file, article_dir)

    if pr_url:
        print(f"\n✅ 完成！PR: {pr_url}")
    else:
        print("\n⚠️ 上传未完成，请检查上方日志")


if __name__ == '__main__':
    main()
