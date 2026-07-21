"""
微信文章下载模块 - 复用 web_analyze 的 download_wechat_advanced
================================
功能:
- 下载微信公众号文章
- 提取正文、图片、公式
- 生成 Markdown 文件

复用来源: C:/MyCode/web_analyze/src/download_wechat_advanced.py
"""

import sys
# 设置输出编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import requests
from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as md
import os
import re
import time
import urllib.parse
from typing import Tuple, Dict, List, Optional
from urllib.parse import urljoin

from utils import find_file_by_basename


class WeChatDownloader:
    """微信公众号文章下载器"""
    
    def __init__(self, output_base: str = None):
        """
        初始化下载器
        
        参数:
            output_base: 输出根目录，默认为项目的 output 目录
        """
        if output_base is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            output_base = os.path.join(project_root, "output")
        
        self.output_base = output_base
        os.makedirs(output_base, exist_ok=True)
        
        print(f"✓ 下载器初始化完成")
        print(f"  - 输出目录: {output_base}")
    
    def download(self, url: str) -> Tuple[str, str, Dict, str]:
        """
        下载微信文章
        
        参数:
            url: 微信文章链接
            
        返回:
            - markdown 内容
            - 文章目录路径
            - 图片映射
            - 文章标题
        """
        print(f"\n🚀 [WeChat] 正在请求文章: {url}")
        
        # 1. 下载 HTML
        html_content = self._fetch_html(url)
        if not html_content:
            return None, None, {}, ""
        
        print("   ✓ HTTP 请求成功")
        
        # 2. 解析 HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 3. 提取标题
        title = self._extract_title(soup, url)
        print(f"\n🧹 正在提取正文...")
        print(f"   ✓ 标题: {title}")
        
        # 4. 创建输出目录
        article_dir, img_dir = self._create_output_structure(title)
        
        # 5. 解析正文
        markdown_content, image_map, warnings = self._parse_article_content(
            soup, img_dir, url
        )

        # 5b. 重编号：img_001/002/003 → pic1/pic2/pic3（全部保留，不做筛选）
        markdown_content, image_map = self._renumber_images(
            markdown_content, image_map, img_dir
        )

        print(f"   ✓ 正文长度: {len(markdown_content)} 字")

        # 6. 保存中文 Markdown
        zh_md_path = self._save_markdown(
            title, markdown_content, image_map, url, article_dir, suffix="_zh"
        )
        
        # 7. 打印统计
        self._print_statistics(image_map, warnings, zh_md_path, article_dir)
        
        return markdown_content, article_dir, image_map, title
    
    def _fetch_html(self, url: str) -> str:
        """下载 HTML 内容"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            return response.text
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            print("   可能原因: 链接已失效 / 需要登录 / 被反爬虫拦截")
            return ""
    
    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        """提取文章标题"""
        # 优先 meta 标签
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content']
        
        # 尝试 h1
        h1 = soup.find('h1', class_='rich_media_title')
        if h1:
            return h1.get_text(strip=True)
        
        # 回退 title 标签
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text(strip=True)
        
        return f"wechat_article_{int(time.time())}"
    
    def _create_output_structure(self, title: str) -> Tuple[str, str]:
        """创建输出目录"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        folder_name = f"article_{timestamp}"
        
        article_dir = os.path.join(self.output_base, folder_name)
        img_dir = os.path.join(article_dir, "images")
        
        os.makedirs(article_dir, exist_ok=True)
        os.makedirs(img_dir, exist_ok=True)
        
        return article_dir, img_dir
    
    def _parse_article_content(self, soup: BeautifulSoup, img_dir: str, 
                               base_url: str) -> Tuple[str, Dict, List]:
        """解析文章内容"""
        content_div = soup.find('div', class_='rich_media_content')
        if not content_div:
            content_div = soup.find('div', id='js_content')
        if not content_div:
            content_div = soup.find('div', class_='rich_media_area_primary')
        
        if not content_div:
            print("❌ 提取失败: 未能找到正文内容")
            return "", {}, []
        
        markdown_parts = []
        image_map = {}
        warnings = []
        img_counter = 1
        
        all_imgs = content_div.find_all('img')
        print(f"🔍 页面中检测到 {len(all_imgs)} 个 <img> 标签")
        
        markdown_parts.append("> 来源: " + base_url + "\n")
        markdown_parts.append("> \n")
        markdown_parts.append("> ⚠️ 公式已自动提取，建议手动校对\n")
        markdown_parts.append("> ⚠️ 音视频内容已跳过（详见文末）\n")
        markdown_parts.append("\n---\n\n")
        
        for element in content_div.find_all(recursive=False):
            md_part, img_counter, image_map_part, warnings_part = self._convert_element(
                element, img_counter, img_dir, base_url
            )
            
            if md_part:
                markdown_parts.append(md_part)
            if image_map_part:
                image_map.update(image_map_part)
            if warnings_part:
                warnings.extend(warnings_part)
        
        if warnings:
            markdown_parts.append("\n---\n\n")
            markdown_parts.append("## 跳过的内容（音视频等不支持的元素）\n")
            for warning in warnings:
                markdown_parts.append(f"- {warning}\n")
        
        return ''.join(markdown_parts), image_map, warnings
    
    def _convert_element(self, element: Tag, img_counter: int, 
                        img_dir: str, base_url: str) -> Tuple[str, int, Dict, List]:
        """转换单个 HTML 元素"""
        image_map = {}
        warnings = []
        
        # 跳过隐藏元素
        if element.get('style', '').find('display:none') >= 0:
            return "", img_counter, {}, []
        
        # 公式
        formula_md = self._extract_formula(element)
        if formula_md:
            return formula_md + "\n\n", img_counter, {}, []
        
        # 图片处理
        all_imgs = element.find_all('img') if element.name != 'img' else []
        
        # 直接处理 img 标签
        if element.name == 'img':
            print(f"   ✓ 处理直接 img 标签")
            md_part, img_counter, img_map = self._process_image(
                element, img_counter, img_dir, base_url
            )
            if img_map:
                image_map.update(img_map)
            return md_part, img_counter, image_map, []
        
        # 音视频检查
        if element.name in ['audio', 'video', 'iframe', 'section']:
            warning = self._check_media_content(element)
            if warning:
                warnings.append(warning)
                return f"[{warning}]\n\n", img_counter, {}, warnings
        
        # 预处理：替换嵌套公式和图片为占位符，防止 markdownify 丢弃
        has_nested = all_imgs or self._has_nested_formulas(element)
        if has_nested:
            if all_imgs:
                print(f"   ✓ 在 <{element.name}> 中发现 {len(all_imgs)} 个嵌套 img")
            element_copy = BeautifulSoup(str(element), 'html.parser').find(element.name)

            # 提取嵌套的行内公式，替换为占位符
            formula_placeholders = self._replace_nested_formulas(element_copy)
            if formula_placeholders:
                print(f"   ✓ 在 <{element.name}> 中发现 {len(formula_placeholders)} 个嵌套公式")

            # 提取嵌套图片，替换为占位符
            img_placeholders = []
            for img_tag in element_copy.find_all('img'):
                img_url = img_tag.get('data-src') or img_tag.get('src') or img_tag.get('data-original')
                if img_url:
                    img_url = urljoin(base_url, img_url)
                    local_filename = f"img_{img_counter:03d}"
                    local_path, success = self._download_image(img_url, local_filename, img_dir)
                    placeholder = f"[IMG_PLACEHOLDER_{img_counter}]"
                    img_tag.replace_with(placeholder)
                    img_placeholders.append((img_counter, local_path))
                    image_map[local_filename] = (img_url, success)
                    img_counter += 1

            # markdownify 转换
            md_content = md(str(element_copy), heading_style="atx",
                            bullets="-", convert=['p', 'ul', 'ol', 'li', 'br', 'hr', 'em', 'strong'])

            # 恢复公式占位符
            for placeholder, formula_md in formula_placeholders:
                # markdownify 可能转义下划线
                escaped = placeholder.replace('_', '\\_')
                md_content = md_content.replace(escaped, formula_md)
                md_content = md_content.replace(placeholder, formula_md)

            # 恢复图片占位符
            for img_num, local_path in img_placeholders:
                placeholder_escaped = f"[IMG\\_PLACEHOLDER\\_{img_num}]"
                placeholder_raw = f"[IMG_PLACEHOLDER_{img_num}]"
                img_md = f"![图{img_num}]({local_path})"
                md_content = md_content.replace(placeholder_escaped, img_md)
                md_content = md_content.replace(placeholder_raw, img_md)
        else:
            # 普通文本转换
            md_content = md(str(element), heading_style="atx",
                            bullets="-", convert=['p', 'ul', 'ol', 'li', 'br', 'hr', 'em', 'strong'])
        
        md_content = re.sub(r'\n{3,}', '\n\n', md_content)
        
        return md_content + "\n\n", img_counter, image_map, warnings
    
    def _extract_formula(self, element: Tag) -> str:
        """提取 MathJax/LaTeX 公式（支持 script、span、data-math 等多种格式）"""
        formula_text = ""

        # 1) <script type="math/tex"> — 最可靠，直接是 LaTeX 源码
        if element.name == 'script' and element.get('type', '').startswith('math/tex'):
            formula_text = element.get_text(strip=True)
            if formula_text:
                return (
                    f"$$\n{formula_text}\n$$"
                    if 'mode=display' in element.get('type', '')
                    else f"\\({formula_text}\\)"
                )

        # 2) <span data-math="..."> / <span data-latex="..."> — 部分微信编辑器格式
        if element.name == 'span':
            formula_text = element.get('data-math') or element.get('data-latex') or ''
            if formula_text:
                return self._fmt_formula(formula_text, element)

            # 3) MathJax 渲染后的 <span> — 尝试从嵌套 script 或 data 属性提取
            classes = element.get('class', [])
            class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)

            is_math_span = any(
                kw in class_str for kw in (
                    'mjx-container', 'math-display', 'mjx-inline',
                    'math-inline', 'MathJax', 'mathjax',
                )
            )

            if is_math_span:
                # 3a) 嵌套的 <script> 标签（微信常见）
                script = element.find(
                    'script', type=lambda t: t and 'math/tex' in (t or '')
                )
                if script:
                    formula_text = script.get_text(strip=True)
                    if formula_text:
                        return self._fmt_formula(formula_text, element)

                # 3b) data-math 在子元素上
                math_child = element.find(
                    attrs={'data-math': True}
                ) or element.find(attrs={'data-latex': True})
                if math_child:
                    formula_text = math_child.get('data-math') or math_child.get('data-latex') or ''
                    if formula_text:
                        return self._fmt_formula(formula_text, element)

                # 3c) 文本提取（兜底 — MathJax 渲染产物可能没有 LaTeX 源码）
                formula_text = self._extract_formula_text(element)
                if formula_text:
                    return self._fmt_formula(formula_text, element)

                # 未提取到任何内容 — 打印元素结构帮助调试
                self._log_unmatched_formula(element)

        return ""

    def _fmt_formula(self, text: str, element: Tag) -> str:
        """根据元素 class 判断是块级还是行内公式并格式化"""
        classes = element.get('class', [])
        class_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
        is_display = any(
            kw in class_str for kw in (
                'math-display', 'mjx-container', 'mode=display',
            )
        )
        if is_display:
            return f"$$\n{text}\n$$"
        return f"\\({text}\\)"

    def _extract_formula_text(self, element: Tag) -> str:
        """从公式元素提取文本（过滤掉纯空白和过长内容）"""
        text = element.get_text(separator=' ', strip=True)
        if text and len(text) < 200:
            return text
        return ""

    # 跟踪未匹配的公式元素，同一种只打一次日志
    _unmatched_formula_tags: set = set()

    def _log_unmatched_formula(self, element: Tag):
        """记录未提取到内容的公式元素，帮助定位新型格式"""
        tag_sig = str(element)[:120]
        if tag_sig not in self._unmatched_formula_tags:
            self._unmatched_formula_tags.add(tag_sig)
            print(f"   🔍 [公式调试] 未提取到内容: {tag_sig}...")

    # ------------------------------------------------------------------
    # 嵌套公式占位符（防止 markdownify 丢弃 MathJax 元素）
    # ------------------------------------------------------------------

    def _has_nested_formulas(self, element: Tag) -> bool:
        """检查元素内是否包含需要提取的公式子元素"""
        # 找 script[type*="math/tex"]
        if element.find('script', type=lambda t: t and 'math/tex' in (t or '')):
            return True
        # 找 MathJax span
        for span in element.find_all('span'):
            classes = ' '.join(span.get('class', [])) if isinstance(
                span.get('class'), list) else str(span.get('class', ''))
            if any(kw in classes for kw in (
                'mjx-', 'MathJax', 'mathjax',
                'math-inline', 'math-display',
            )):
                return True
        return False

    def _replace_nested_formulas(self, element_copy: Tag) -> list:
        """
        在元素副本中查找所有嵌套公式，替换为占位符。

        返回: [(placeholder_str, formula_markdown), ...]
        """
        placeholders = []
        idx = 0

        # 1) script[type*="math/tex"]
        for script in element_copy.find_all(
            'script', type=lambda t: t and 'math/tex' in (t or '')
        ):
            formula_md = self._extract_formula(script)
            if formula_md:
                placeholder = f'[FORMULA_NESTED_{idx}]'
                script.replace_with(placeholder)
                placeholders.append((placeholder, formula_md))
                idx += 1

        # 2) MathJax span
        for span in element_copy.find_all('span'):
            classes = ' '.join(span.get('class', [])) if isinstance(
                span.get('class'), list) else str(span.get('class', ''))
            if any(kw in classes for kw in (
                'mjx-', 'MathJax', 'mathjax',
                'math-inline', 'math-display',
            )):
                formula_md = self._extract_formula(span)
                if formula_md:
                    placeholder = f'[FORMULA_NESTED_{idx}]'
                    span.replace_with(placeholder)
                    placeholders.append((placeholder, formula_md))
                    idx += 1

        return placeholders
    
    def _process_image(self, img_tag: Tag, img_counter: int, 
                       img_dir: str, base_url: str) -> Tuple[str, int, Dict]:
        """处理图片"""
        img_url = img_tag.get('data-src') or img_tag.get('src') or img_tag.get('data-original')
        
        print(f"   🔍 [图片{img_counter}] URL: {img_url[:50] if img_url else 'None'}")
        
        if not img_url:
            print(f"   ❌ [图片{img_counter}] 未找到有效的图片URL")
            return "", img_counter, {}
        
        img_url = urljoin(base_url, img_url)
        
        local_filename = f"img_{img_counter:03d}"
        local_path, success = self._download_image(img_url, local_filename, img_dir)
        
        md_placeholder = f"![图{img_counter}]({local_path})\n"
        image_map = {local_filename: (img_url, success)}
        
        return md_placeholder, img_counter + 1, image_map
    
    def _download_image(self, img_url: str, filename: str, img_dir: str) -> Tuple[str, bool]:
        """下载图片"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://mp.weixin.qq.com/"
        }
        
        ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1]
        if not ext or len(ext) > 5:
            ext = '.png'
        
        local_filename = f"{filename}{ext}"
        local_path = os.path.join(img_dir, local_filename)
        
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(img_url, headers=headers, timeout=10, stream=True)
                response.raise_for_status()
                
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                if os.path.getsize(local_path) > 0:
                    return f"images/{local_filename}", True
                    
            except Exception as e:
                if attempt == max_retries:
                    print(f"   ⚠️ 下载失败 ({filename}): {e}")
                    return img_url, False
                time.sleep(1)
        
        return img_url, False
    
    def _check_media_content(self, element: Tag) -> str:
        """检查音视频内容"""
        if element.name == 'audio':
            return "[00:00] 音频内容（微信语音消息）"
        
        if element.name == 'video':
            return "[00:00] 视频内容"
        
        if element.name == 'iframe':
            src = element.get('src', '')
            if 'qq.com' in src or 'bilibili.com' in src or 'youku.com' in src:
                return f"[00:00] 视频内容（{urllib.parse.urlparse(src).netloc}）"
        
        if element.name == 'section':
            if element.find('audio'):
                return "[00:00] 音频内容（微信语音消息）"
            if element.find('video') or element.find('iframe'):
                return "[00:00] 视频内容"
        
        return ""
    
    def _save_markdown(self, title: str, markdown: str, image_map: Dict,
                       url: str, article_dir: str,
                       suffix: str = "_zh") -> str:
        """保存 Markdown 文件"""
        safe_title = "".join([c for c in title if c not in r'/:*?"<>|']).strip()[:80]
        md_filename = f"{safe_title}{suffix}.md"
        md_path = os.path.join(article_dir, md_filename)
        
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n")
            f.write(markdown)
        
        # 保存图片映射
        map_filename = f"{safe_title}.images_map.txt"
        map_path = os.path.join(article_dir, map_filename)
        
        with open(map_path, 'w', encoding='utf-8') as f:
            f.write(f"# 图片映射文件\n")
            f.write(f"# 原始文章: {url}\n")
            f.write(f"# 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            for local_name, (original_url, success) in sorted(image_map.items()):
                if success:
                    f.write(f"{local_name} | {original_url}\n")
                else:
                    f.write(f"{local_name} | [下载失败] {original_url}\n")
        
        return md_path
    
    def _renumber_images(self, markdown: str, image_map: Dict,
                         img_dir: str) -> Tuple[str, Dict]:
        """
        将所有下载图片按 markdown 中出现顺序重编号为 pic1, pic2, pic3...
        同步更新：磁盘文件、markdown 引用、正文图注标签、image_map。

        例如: img_001 → pic1, img_002 → pic2, img_003 → pic3
              ![图1] → ![图1],  文件名和编号全部对齐
        """
        # 1. 按出现顺序找出所有图片引用
        img_pattern = re.compile(
            r'!\[(图\d+)\]\(images/(img_\d+)(\.\w+)\)'
        )
        matches = img_pattern.findall(markdown)

        if not matches:
            return markdown, image_map

        # 2. 构建 old → new 映射
        mapping: Dict[str, dict] = {}
        for new_idx, (old_fig, old_basename, ext) in enumerate(matches, 1):
            mapping[old_basename] = {
                'old_fig': old_fig,
                'new_fig': f'图{new_idx}',
                'new_basename': f'pic{new_idx}',
                'new_filename': f'pic{new_idx}{ext}',
                'ext': ext,
            }

        # 3. 重命名磁盘上的图片文件
        for old_basename, info in mapping.items():
            old_path = self._find_image_by_basename(img_dir, old_basename)
            if old_path:
                new_path = os.path.join(img_dir, info['new_filename'])
                if old_path != new_path:
                    os.rename(old_path, new_path)

        # 4. 替换 markdown 中的图片引用: ![图N](images/img_NNN.ext) → ![图M](images/picM.ext)
        new_md = markdown
        for old_basename, info in mapping.items():
            old_ref = (
                f'![{info["old_fig"]}](images/{old_basename}{info["ext"]})'
            )
            new_ref = (
                f'![{info["new_fig"]}](images/{info["new_filename"]})'
            )
            new_md = new_md.replace(old_ref, new_ref)

        # 5. 替换正文中的图注标签（不在图片引用内的 图N → 图M）
        #    先替换长标签避免冲突（如图12 先于 图1）
        for old_basename, info in sorted(
            mapping.items(),
            key=lambda x: -len(x[1]['old_fig'])
        ):
            old_label = info['old_fig']
            new_label = info['new_fig']
            if old_label == new_label:
                continue
            # 图N 不在 ![...] 上下文中，且不以数字继续
            new_md = re.sub(
                rf'(?<!!\[)(?<!\w){re.escape(old_label)}(?!\d)',
                new_label,
                new_md,
            )

        # 6. 重建 image_map: 用新 key 替换旧 key
        new_image_map = {}
        for old_key, value in image_map.items():
            if old_key in mapping:
                new_key = mapping[old_key]['new_basename']
                new_image_map[new_key] = value
            else:
                # 已被过滤但仍在 map 中的（不太可能，但安全处理）
                pass

        print(f"   🔢 图片重编号: {len(mapping)} 张 → "
              f"pic1~pic{len(mapping)}")

        return new_md, new_image_map

    @staticmethod
    def _find_image_by_basename(img_dir: str, basename: str) -> Optional[str]:
        """根据 basename（不含扩展名）找到实际文件路径（委托 utils）"""
        return find_file_by_basename(img_dir, basename)

    def _print_statistics(self, image_map: Dict, warnings: List,
                          md_path: str, article_dir: str):
        """打印统计信息"""
        print(f"\n📸 图片统计:")
        
        total_imgs = len(image_map)
        success_imgs = sum(1 for _, success in image_map.values() if success)
        failed_imgs = total_imgs - success_imgs
        
        print(f"   ✓ 找到 {total_imgs} 张图片")
        if total_imgs > 0:
            print(f"   ✓ 成功下载: {success_imgs} 张")
            if failed_imgs > 0:
                print(f"   ⚠️ 下载失败: {failed_imgs} 张")
        
        if warnings:
            print(f"\n⚠️ 警告: 发现 {len(warnings)} 处音视频内容，已跳过")
        
        print(f"\n🎉 成功保存!")
        print(f"   - Markdown: {os.path.basename(md_path)}")
        print(f"   - 保存位置: {article_dir}")


def test_downloader():
    """测试下载器"""
    print("=" * 50)
    print("下载器测试")
    print("=" * 50)
    
    downloader = WeChatDownloader()
    
    # 测试 URL（需要提供真实的微信文章链接）
    test_url = input("请输入微信文章链接进行测试: ").strip()
    
    if test_url:
        markdown, article_dir, image_map, title = downloader.download(test_url)
        if markdown:
            print(f"\n✓ 测试成功")
            print(f"  - 内容长度: {len(markdown)}")
            print(f"  - 图片数量: {len(image_map)}")


if __name__ == "__main__":
    test_downloader()