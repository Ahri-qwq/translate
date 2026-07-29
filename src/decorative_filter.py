import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

"""
装饰图 pHash 过滤器
===================
基于感知哈希的装饰图黑名单过滤。
- DecorativeFilter: 运行时过滤器，供 downloader 调用
- build_hash_library(): 从样本文件夹生成哈希库 JSON
- CLI: python src/decorative_filter.py --build
"""

import imagehash
from PIL import Image
import json
import os
import re
import argparse
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

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp'}


class DecorativeFilter:
    """基于感知哈希的装饰图过滤器"""

    def __init__(self, hash_library_path: str = None,
                 threshold: int = DEFAULT_THRESHOLD):
        """
        参数:
            hash_library_path: 哈希库 JSON 路径，默认 models/decorative_hashes.json
            threshold:         汉明距离阈值，≤ 此值视为匹配（默认 5）
        """
        if hash_library_path is None:
            hash_library_path = DEFAULT_HASH_LIB

        self.hash_library_path = hash_library_path
        self.threshold = threshold
        self.known_hashes: list = []
        self._load()

    def _load(self):
        """从 JSON 文件加载哈希库到内存"""
        self.known_hashes = []
        if os.path.exists(self.hash_library_path):
            with open(self.hash_library_path, 'r', encoding='utf-8') as f:
                self.known_hashes = json.load(f)
            print(f"   🧹 装饰图过滤器: 已加载 {len(self.known_hashes)} 条哈希")
        else:
            print(f"   🧹 装饰图过滤器: 哈希库不存在 "
                  f"({self.hash_library_path})，跳过过滤")

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
                target_hash = imagehash.hex_to_hash(entry["hash"])
                distance = img_hash - target_hash
            except Exception:
                continue
            if distance <= self.threshold:
                return True, entry.get("label", "unknown")

        return False, None

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
                # 目标已存在则先删除（Windows 上 rename 不允许覆盖）
                if os.path.exists(dest):
                    os.remove(dest)
                os.rename(img_path, dest)
            except OSError:
                pass  # 移动失败不阻塞流程

            # 从 map 中删除
            del new_map[basename]

            # 从 markdown 中删除该图片引用行:
            #   格式: ![图N](images/picN.ext) 或 ![图N](images/img_NNN.ext)
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
        # 如果过滤后以空行开头，去掉
        new_md = new_md.lstrip('\n')

        return new_md, new_map, filtered_count, filtered_labels


def _find_image_by_basename(directory: str, basename: str) -> Optional[str]:
    """根据 basename（不含扩展名）找到实际文件路径"""
    for ext in IMAGE_EXTENSIONS:
        fpath = os.path.join(directory, f'{basename}{ext}')
        if os.path.exists(fpath):
            return fpath
    return None


def build_hash_library(samples_dir: str = None,
                       output_file: str = None) -> int:
    """
    扫描 samples_dir 下所有图片，计算 pHash，写入 JSON 哈希库。
    图片直接平放在目录中即可，无需分类子文件夹。

    参数:
        samples_dir: 样本图片目录（默认 data/decorative_samples/）
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
        print(f"   请创建目录并放入装饰图:")
        print(f"   mkdir {samples_dir}")
        return 0

    entries = []

    for fname in sorted(os.listdir(samples_dir)):
        fpath = os.path.join(samples_dir, fname)
        if os.path.isdir(fpath):
            continue  # 跳过子文件夹（兼容旧结构）

        ext = os.path.splitext(fname)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            continue

        try:
            img_hash = imagehash.phash(Image.open(fpath))
        except Exception as e:
            print(f"   ⚠️ 跳过 {fname}: {e}")
            continue

        entries.append({
            "hash": str(img_hash),
            "label": "decorative",
            "source": fname,
        })
        print(f"   ✓ {fname} → {img_hash}")

    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 哈希库已生成: {output_file}")
    print(f"   {len(entries)} 张装饰图")

    return len(entries)


# ===================================================================
# CLI 入口
# ===================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="装饰图 pHash 过滤器 - 构建哈希黑名单库"
    )
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
            print("   💡 提示: 将装饰图放入上述目录后重新运行即可")
            sys.exit(0)
    else:
        parser.print_help()
