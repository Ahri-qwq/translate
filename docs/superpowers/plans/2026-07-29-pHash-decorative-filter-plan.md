# 装饰图 pHash 过滤 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 pHash 装饰图过滤器，在下载阶段自动将模板装饰图移到 `_filtered/` 并从 markdown 中移除引用。

**Architecture:** 新建 `src/decorative_filter.py` 作为独立模块，包含 `DecorativeFilter` 类（运行时过滤）和 `build_hash_library()` 函数（从样本文件夹生成 JSON 哈希库）。在 `downloader.py` 的 `download()` 方法中，`_renumber_images()` 之后插入一次调用。

**Tech Stack:** Python 3, imagehash, Pillow

## Global Constraints

- pHash 汉明距离阈值 ≤ 5 视为匹配
- 过滤行为：移到 `images/_filtered/`，不直接删除
- 哈希库不存在时静默跳过，不阻断下载流程
- 项目依赖部分：imagehash、Pillow

---

### Task 1: 安装依赖

**Files:**
- 无需创建（pip 安装）

**Interfaces:**
- Consumes: 无
- Produces: `imagehash` 和 `Pillow` 在环境中可用

- [ ] **Step 1: 安装 imagehash**

```bash
pip install imagehash Pillow
```

- [ ] **Step 2: 验证安装**

```bash
python -c "import imagehash; from PIL import Image; print('OK')"
```

预期输出: `OK`

---

### Task 2: 实现 src/decorative_filter.py

**Files:**
- Create: `src/decorative_filter.py`

**Interfaces:**
- Consumes: 无（无前置任务依赖）
- Produces:
  - `class DecorativeFilter(**opts)` — `.is_decorative(image_path: str) -> Tuple[bool, str | None]`、`.filter_images(img_dir: str, image_map: Dict, markdown: str) -> Tuple[str, Dict, int, list]`
  - `def build_hash_library(samples_dir: str, output_file: str) -> int` — 返回生成的条目数
  - CLI: `--build` / `--samples` / `--output`

- [ ] **Step 1: 创建文件骨架**

```python
"""
装饰图 pHash 过滤器
===================
基于感知哈希的装饰图黑名单过滤。
- DecorativeFilter: 运行时过滤器，供 downloader 调用
- build_hash_library(): 从样本文件夹生成哈希库 JSON
"""

import imagehash
from PIL import Image
import json
import os
import sys
from typing import Dict, Tuple, List, Optional


# --- 路径常量 ---
DEFAULT_SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "decorative_samples",
)
DEFAULT_HASH_LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "decorative_hashes.json",
)
DEFAULT_THRESHOLD = 5
```

- [ ] **Step 2: 实现 DecorativeFilter 类**

```python
class DecorativeFilter:
    """基于感知哈希的装饰图过滤器"""

    def __init__(self, hash_library_path: str = None, threshold: int = DEFAULT_THRESHOLD):
        """
        参数:
            hash_library_path: 哈希库 JSON 路径，默认 models/decorative_hashes.json
            threshold:         汉明距离阈值，≤ 此值视为匹配（默认 5）
        """
        if hash_library_path is None:
            hash_library_path = DEFAULT_HASH_LIB

        self.threshold = threshold
        self.known_hashes: list = []

        if os.path.exists(hash_library_path):
            with open(hash_library_path, 'r', encoding='utf-8') as f:
                self.known_hashes = json.load(f)
            print(f"   🧹 装饰图过滤器: 已加载 {len(self.known_hashes)} 条哈希")
        else:
            print(f"   🧹 装饰图过滤器: 哈希库不存在 ({hash_library_path})，跳过过滤")

    def is_decorative(self, image_path: str) -> Tuple[bool, Optional[str]]:
        """
        判断单张图片是否为装饰图。
        返回: (is_decorative, matched_label | None)
        """
        if not self.known_hashes:
            return False, None

        try:
            img_hash = imagehash.phash(Image.open(image_path))
        except Exception:
            return False, None

        for entry in self.known_hashes:
            try:
                distance = img_hash - imagehash.hex_to_hash(entry["hash"])
            except Exception:
                continue
            if distance <= self.threshold:
                return True, entry.get("label", "unknown")

        return False, None
```

- [ ] **Step 3: 实现 filter_images 批量过滤方法**

```python
    def filter_images(self, img_dir: str, image_map: Dict,
                      markdown: str) -> Tuple[str, Dict, int, list]:
        """
        对 image_map 中所有图片做装饰图过滤。
        命中则文件移至 images/_filtered/，markdown 引用删除。

        参数:
            img_dir:   images 目录路径
            image_map: {basename_without_ext: (url, success)}
            markdown:  当前 markdown 正文

        返回:
            (new_markdown, new_image_map, filtered_count, filtered_labels)
        """
        if not self.known_hashes:
            return markdown, image_map, 0, []

        import re

        filtered_dir = os.path.join(img_dir, "_filtered")
        new_md = markdown
        new_map = dict(image_map)
        filtered_count = 0
        filtered_labels: list = []

        for basename in list(image_map.keys()):
            # 找到磁盘上的实际文件
            img_path = _find_image_by_basename(img_dir, basename)
            if img_path is None:
                continue

            is_dec, label = self.is_decorative(img_path)
            if not is_dec:
                continue

            # 移动文件到 _filtered/
            os.makedirs(filtered_dir, exist_ok=True)
            fname = os.path.basename(img_path)
            dest = os.path.join(filtered_dir, fname)
            try:
                os.rename(img_path, dest)
            except OSError:
                pass  # 移动失败不阻塞流程

            # 从 map 中删除
            del new_map[basename]

            # 从 markdown 中删除该图片引用行:
            #   ![图N](images/picN.ext)
            #   ![图N](images/img_NNN.ext)
            escaped = re.escape(basename)
            new_md = re.sub(
                rf'!\[图\d+\]\(images/{escaped}\.\w+\)\s*\n?',
                '',
                new_md,
            )

            filtered_count += 1
            filtered_labels.append(label)
            print(f"   🧹 过滤装饰图: {fname} ({label})")

        # 清理因删除引用产生的连续空行
        new_md = re.sub(r'\n{3,}', '\n\n', new_md)

        # 如果过滤后 markdown 以空行开头，去掉
        new_md = new_md.lstrip('\n')

        return new_md, new_map, filtered_count, filtered_labels


def _find_image_by_basename(directory: str, basename: str) -> Optional[str]:
    """根据 basename（不含扩展名）找到实际文件"""
    IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']
    for ext in IMAGE_EXTENSIONS:
        fpath = os.path.join(directory, f'{basename}{ext}')
        if os.path.exists(fpath):
            return fpath
    return None
```

- [ ] **Step 4: 实现 build_hash_library() 函数**

```python
def build_hash_library(samples_dir: str = None, output_file: str = None) -> int:
    """
    扫描 samples_dir 下的子文件夹，为每张图片计算 pHash，
    写入 JSON 哈希库。子文件夹名自动作为 label。

    参数:
        samples_dir: 样本图片根目录（默认 data/decorative_samples/）
        output_file: 输出 JSON 路径（默认 models/decorative_hashes.json）

    返回:
        生成的哈希条目数
    """
    if samples_dir is None:
        samples_dir = DEFAULT_SAMPLES_DIR
    if output_file is None:
        output_file = DEFAULT_HASH_LIB

    if not os.path.isdir(samples_dir):
        print(f"❌ 样本目录不存在: {samples_dir}")
        print(f"   请创建目录并按类型放入装饰图，例如:")
        print(f"   {samples_dir}/banner_top/")
        print(f"   {samples_dir}/divider/")
        print(f"   {samples_dir}/qr_code/")
        return 0

    IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}
    entries = []

    for label in sorted(os.listdir(samples_dir)):
        subdir = os.path.join(samples_dir, label)
        if not os.path.isdir(subdir):
            continue

        for fname in sorted(os.listdir(subdir)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue

            fpath = os.path.join(subdir, fname)
            try:
                img_hash = imagehash.phash(Image.open(fpath))
            except Exception as e:
                print(f"   ⚠️ 跳过 {fpath}: {e}")
                continue

            entries.append({
                "hash": str(img_hash),
                "label": label,
                "source": fname,
            })
            print(f"   ✓ {label}/{fname} → {img_hash}")

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 哈希库已生成: {output_file}")
    print(f"   {len(entries)} 条记录，{len(set(e['label'] for e in entries))} 个标签")

    return len(entries)
```

- [ ] **Step 5: 实现 argparse CLI 入口**

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="装饰图 pHash 过滤器")
    parser.add_argument(
        "--build", action="store_true",
        help="从样本文件夹重建哈希库"
    )
    parser.add_argument(
        "--samples", type=str, default=DEFAULT_SAMPLES_DIR,
        help=f"样本文件夹路径（默认: {DEFAULT_SAMPLES_DIR}）"
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_HASH_LIB,
        help=f"输出 JSON 路径（默认: {DEFAULT_HASH_LIB}）"
    )
    args = parser.parse_args()

    if args.build:
        count = build_hash_library(args.samples, args.output)
        if count == 0:
            sys.exit(1)
    else:
        parser.print_help()
```

- [ ] **Step 6: 验证命令行能正常启动**

Run:
```bash
python src/decorative_filter.py --help
```
预期输出: help 信息

Run:
```bash
python src/decorative_filter.py --build
```
预期: 提示样本目录不存在（因为你还没放图），但不会报错崩溃。

---

### Task 3: 集成到 downloader.py

**Files:**
- Modify: `src/downloader.py`

**Interfaces:**
- Consumes: `DecorativeFilter` from `src/decorative_filter.py`
- Produces: 下载流程中自动过滤装饰图

- [ ] **Step 1: 在 downloader.py 顶部添加 import**

找到文件顶部的 import 区域（约第 27 行），在 `from utils import find_file_by_basename` 之后添加：

```python
from decorative_filter import DecorativeFilter
```

- [ ] **Step 2: 在 __init__ 中初始化过滤器**

找到 `WeChatDownloader.__init__()` 方法（约第 33 行），在 `os.makedirs(output_base, exist_ok=True)` 之后、`print(f"✓ 下载器初始化完成")` 之前添加：

```python
        # 初始化装饰图过滤器
        self.decorative_filter = DecorativeFilter()
```

- [ ] **Step 3: 在 download() 中插入过滤调用**

找到 `download()` 方法中，`_renumber_images()` 调用之后（约第 89-92 行）：

```python
        # 5b. 重编号：img_001/002/003 → pic1/pic2/pic3（全部保留，不做筛选）
        markdown_content, image_map = self._renumber_images(
            markdown_content, image_map, img_dir
        )
```

在其后插入：

```python
        # 5c. 装饰图过滤：基于 pHash 黑名单过滤模板装饰图
        markdown_content, image_map, filtered_count, __ = (
            self.decorative_filter.filter_images(
                img_dir, image_map, markdown_content
            )
        )
        if filtered_count:
            print(f"   🧹 共过滤 {filtered_count} 张装饰图 → images/_filtered/")
```

- [ ] **Step 4: 验证修改不影响现有流程**

Run:
```bash
python -c "from src.downloader import WeChatDownloader; d = WeChatDownloader(); print('OK')"
```
预期输出: 下载器初始化成功，显示过滤器状态

---

### Task 4: 端到端验证

**Files:**
- 无新文件

- [ ] **Step 1: 准备样本数据**

将你手动标记的装饰图按类型放入子文件夹：

```bash
mkdir -p data/decorative_samples/banner_top
mkdir -p data/decorative_samples/divider
mkdir -p data/decorative_samples/qr_code
mkdir -p data/decorative_samples/footer_banner

# 把你已标记的图片复制到对应子文件夹
```

- [ ] **Step 2: 构建哈希库**

```bash
python src/decorative_filter.py --build
```

- [ ] **Step 3: 运行一次完整下载，观察过滤效果**

```bash
python src/main.py --url "微信文章链接" --download-only
```

观察输出中是否有 `🧹 过滤装饰图` 日志，以及 `images/_filtered/` 目录中是否有被过滤的图片。

- [ ] **Step 4: 验证过滤结果**

检查：
- `images/_filtered/` 中是否有图片（被过滤的装饰图）
- `images/` 中是否只保留了正文配图
- 生成的 `_zh.md` 中是否已无装饰图引用
