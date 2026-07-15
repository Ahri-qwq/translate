"""
OSS 图片上传模块
===============
使用 ossutil CLI 将本地图片上传到阿里云 OSS，生成 HTTPS 访问地址。

设计原则:
- 零额外依赖：直接调用 ossutil 命令行，不引入 OSS Python SDK
- 新环境友好：AK 通过 -i/-k 参数传入，不依赖 ~/.ossutilconfig 配置文件
- 容错：上传失败时保留原始 URL，不阻塞流水线

前置条件: 已安装 ossutil 2.0 并加入了 PATH
"""

import glob
import os
import re
import subprocess
import sys
import urllib.parse
from typing import Dict, Optional, Tuple

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


class OSSUploader:
    """阿里云 OSS 图片上传器 —— 封装 ossutil 命令行"""

    def __init__(self, config: dict):
        """
        参数:
            config: OSS 配置字典，需包含:
                access_key_id, access_key_secret, bucket,
                endpoint, region, path_prefix (可选)
        """
        self.ak_id = config['access_key_id']
        self.ak_secret = config['access_key_secret']
        self.bucket = config['bucket']
        self.endpoint = config['endpoint']
        self.region = config.get('region', '')
        self.path_prefix = config.get('path_prefix', '').rstrip('/')

        self._ossutil_exe = self._find_ossutil()

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def upload_and_update_map(
        self,
        article_dir: str,
        image_map: Dict[str, Tuple[str, bool]],
        oss_folder: str,
    ) -> Dict[str, str]:
        """
        上传文章图片到 OSS 并重写 images_map.txt。

        参数:
            article_dir: 文章输出目录（含 images/ 子目录和 images_map.txt）
            image_map:   下载器返回的 {local_name: (original_url, success)}
            oss_folder:  OSS 上的目标文件夹名（如 "DeePMD-kit_14_07_2026"）
        """
        images_dir = os.path.join(article_dir, 'images')
        map_file = self._find_map_file(article_dir)

        if not os.path.isdir(images_dir):
            print(f"  ⚠️ 图片目录不存在，跳过 OSS 上传")
            return {}

        # 只上传下载成功的图片
        targets = {}
        for local_name, (original_url, success) in image_map.items():
            if not success:
                continue
            fpath = self._find_local_file(images_dir, local_name)
            if fpath:
                targets[local_name] = fpath

        if not targets:
            print("  ⚠️ 没有可上传的图片（全部下载失败或已过滤）")
            return {}

        # 生成 OSS 路径: {path_prefix}/{oss_folder}/
        oss_subdir = f"{self.path_prefix}/{oss_folder}" if self.path_prefix else oss_folder
        oss_base = f"oss://{self.bucket}/{oss_subdir}"

        print(f"\n  📤 上传图片到 OSS...")
        print(f"     目标: {oss_base}/")
        print(f"     数量: {len(targets)} 张")

        oss_url_map = {}
        success_count = 0

        for local_name, local_path in targets.items():
            fname = os.path.basename(local_path)
            remote_path = f"{oss_base}/{fname}"
            https_url = self._build_https_url(f"{oss_subdir}/{fname}")

            if self._upload_file(local_path, remote_path):
                oss_url_map[local_name] = https_url
                success_count += 1
            else:
                # 保留原始微信 CDN URL 作为 fallback
                oss_url_map[local_name] = image_map[local_name][0]
                print(f"     ⚠️ {local_name} → 回退到原始 URL")

        print(f"     ✓ 成功: {success_count}/{len(targets)}")

        # 重写 images_map.txt
        if map_file and oss_url_map:
            self._rewrite_map_file(map_file, oss_url_map)

        return oss_url_map

    # ------------------------------------------------------------------
    # 内部方法 — 文件定位
    # ------------------------------------------------------------------

    @staticmethod
    def _find_map_file(article_dir: str) -> Optional[str]:
        """在文章目录中定位 images_map.txt"""
        for name in os.listdir(article_dir):
            if name.endswith('.images_map.txt'):
                return os.path.join(article_dir, name)
        return None

    @staticmethod
    def _find_local_file(images_dir: str, basename: str) -> Optional[str]:
        """根据 basename（如 img_001）找到带扩展名的实际文件"""
        for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']:
            fpath = os.path.join(images_dir, f"{basename}{ext}")
            if os.path.exists(fpath):
                return fpath
        return None

    # ------------------------------------------------------------------
    # 内部方法 — ossutil 调用
    # ------------------------------------------------------------------

    def _find_ossutil(self) -> str:
        """查找 ossutil 可执行文件，返回完整路径

        搜索顺序: 1) PATH 中的 ossutil  2) 常见安装目录
        """
        # 1) 先尝试 PATH
        try:
            subprocess.run(
                ['ossutil', 'version'],
                capture_output=True, text=True, timeout=5,
            )
            return 'ossutil'  # PATH 中可用，直接用命令名
        except FileNotFoundError:
            pass
        except Exception:
            return 'ossutil'  # 找到了但执行出错（如网络），仍可用

        # 2) 搜索常见安装目录
        if sys.platform == 'win32':
            search_dirs = [
                r'C:\Program Files (x86)\ossutil-*',
                r'C:\Program Files\ossutil-*',
                os.path.expanduser(r'~\ossutil-*'),
            ]
            for pattern in search_dirs:
                matches = sorted(glob.glob(pattern), reverse=True)  # 新版优先
                for match in matches:
                    exe = os.path.join(match, 'ossutil.exe')
                    if os.path.isfile(exe):
                        return exe

        raise RuntimeError(
            "未找到 ossutil 命令。请先安装 ossutil 2.0:\n"
            "https://help.aliyun.com/zh/oss/developer-reference/ossutil-overview/"
        )

    def _upload_file(self, local_path: str, remote_path: str) -> bool:
        """上传单个文件，成功返回 True"""
        cmd = [
            self._ossutil_exe, 'cp',
            local_path,
            remote_path,
            '-i', self.ak_id,
            '-k', self.ak_secret,
            '-e', self.endpoint,
            '--region', self.region,
            '-f',   # 静默覆盖，不询问
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return True
            else:
                err = result.stderr.strip() if result.stderr else '未知错误'
                print(f"     ❌ {os.path.basename(local_path)}: {err}")
                return False
        except subprocess.TimeoutExpired:
            print(f"     ❌ {os.path.basename(local_path)}: 上传超时")
            return False
        except Exception as e:
            print(f"     ❌ {os.path.basename(local_path)}: {e}")
            return False

    def _build_https_url(self, oss_path: str) -> str:
        """
        构建公开 HTTPS 访问地址。

        oss_path: 不含 bucket 的对象路径
                  （如 "community/Blog Files/Article_Name/img_001.png"）
        """
        encoded = urllib.parse.quote(oss_path, safe='/')
        return f"https://{self.bucket}.{self.endpoint}/{encoded}"

    # ------------------------------------------------------------------
    # 内部方法 — 映射文件
    # ------------------------------------------------------------------

    @staticmethod
    def _rewrite_map_file(map_file: str, url_map: Dict[str, str]):
        """
        重写 images_map.txt，将 URL 替换为 OSS HTTPS 地址。

        文件格式:
            # 注释
            img_001 | https://dp-public.oss-cn-beijing.aliyuncs.com/...
        """
        with open(map_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        updated = []
        for line in lines:
            stripped = line.rstrip('\n')
            if not stripped or stripped.startswith('#'):
                updated.append(stripped)
                continue

            if '|' in stripped:
                key, _ = stripped.split('|', 1)
                key = key.strip()
                if key in url_map:
                    updated.append(f"{key} | {url_map[key]}")
                else:
                    updated.append(stripped)
            else:
                updated.append(stripped)

        with open(map_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(updated) + '\n')


# ===================================================================
# 工厂函数：从 config.yaml 构建上传器
# ===================================================================

def create_uploader(config_path: str = None) -> Optional[OSSUploader]:
    """
    从 config.yaml 读取 OSS 配置，创建 OSSUploader 实例。

    如果未配置 oss 段或 AK 未填写，返回 None（流水线安全跳过）。
    """
    import yaml

    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config.yaml',
        )

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    oss_cfg = cfg.get('oss', {})
    if not oss_cfg:
        return None

    ak_id = oss_cfg.get('access_key_id', '')
    ak_secret = oss_cfg.get('access_key_secret', '')
    if not ak_id or not ak_secret:
        return None

    return OSSUploader(oss_cfg)


# ===================================================================
# 命令行入口（独立测试用）
# ===================================================================

def main():
    """独立测试 OSS 上传功能"""
    import argparse

    parser = argparse.ArgumentParser(description='OSS 图片上传工具')
    parser.add_argument('--dir', required=True, help='文章输出目录')
    parser.add_argument('--config', default=None, help='config.yaml 路径')
    args = parser.parse_args()

    uploader = create_uploader(args.config)
    if uploader is None:
        print("❌ OSS 未配置，请先在 config.yaml 中填写 oss.access_key_id 等信息")
        return

    # 从 images_map.txt 读取映射
    map_file = uploader._find_map_file(args.dir)
    if not map_file:
        print("❌ 未找到 images_map.txt")
        return

    # 手动构建 image_map（模拟下载器返回格式）
    image_map = {}
    with open(map_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '|' in line:
                key, url = line.split('|', 1)
                image_map[key.strip()] = (url.strip(), True)

    # 文件夹名：用目录名（独立测试时无法分类）
    folder = os.path.basename(args.dir.rstrip('/\\'))

    result = uploader.upload_and_update_map(args.dir, image_map, folder)
    print(f"\n✓ 完成，{len(result)} 张图片已上传")


if __name__ == '__main__':
    main()
