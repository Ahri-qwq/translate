# 装饰图 pHash 过滤 — 设计文档

**日期**：2026-07-29
**状态**：已确认

---

## 1. 背景

微信公众号模板装饰图（顶部横幅、分割线、底部二维码等）与正文配图混在一起下载，需要手动删除。同一公众号模板的装饰图片内容完全一致（像素级相同），只是 CDN URL 每次不同。

核心思路：**不是图像识别问题，是已知图片去重/过滤问题**。

## 2. 目标

- 对下载的每张图片计算 pHash，与预建装饰图哈希库比对
- 命中则自动过滤：图片移到 `images/_filtered/`，markdown 中去掉引用
- 哈希库维护成本极低：新装饰图扔文件夹 → 跑脚本重建 → 即时生效

## 3. 设计

### 3.1 架构

```
data/decorative_samples/          ← 人工维护的原始样本（源数据）
├── banner_top/                   ← 文件夹名 = 标签（自动识别）
│   └── xxx.png
├── divider/
│   └── xxx.png
└── ...

     | python src/decorative_filter.py --build
     ▼
models/decorative_hashes.json     ← 一键生成（只读产物）

     | 运行时加载
     ▼
src/decorative_filter.py          ← DecorativeFilter 类
src/downloader.py                 ← 集成点：_renumber_images() 之后
```

### 3.2 新增/修改文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `src/decorative_filter.py` | 新建 | 核心：`DecorativeFilter` 类 + `build_hash_library()` 脚本入口 |
| `src/downloader.py` | 修改 | `download()` 中 `_renumber_images` 之后插入过滤调用 |
| `data/decorative_samples/` | 新建目录 | 按类型建子文件夹，放入装饰图样本 |
| `models/decorative_hashes.json` | 脚本生成 | 不手动编辑 |

### 3.3 集成位置

在 `downloader.py` 的 `download()` 方法中，`_renumber_images()` 之后、`_save_markdown()` 之前插入过滤逻辑：

```
download()
  ├── _parse_article_content()
  ├── _renumber_images()
  ├── ★ 装饰图过滤 ★              ← 新增
  └── _save_markdown()
```

### 3.4 DecorativeFilter API

```python
class DecorativeFilter:
    def __init__(self, hash_library_path="models/decorative_hashes.json", threshold=5)
    def is_decorative(self, image_path: str) -> Tuple[bool, str | None]
    def filter_images(self, img_dir: str, image_map: Dict, markdown: str) -> Tuple[str, Dict, int]
```

- `is_decorative()`：计算 pHash → 遍历黑名单比对汉明距离 → 返回 (是否命中, 标签)
- `filter_images()`：遍历 image_map → 命中则文件移到 `_filtered/` → 去掉 markdown 引用 → 返回 (新md, 新map, 过滤数量)

### 3.5 命令行脚本

```bash
# 从 data/decorative_samples/ 扫描所有子文件夹，生成 JSON
python src/decorative_filter.py --build

# 从指定目录构建
python src/decorative_filter.py --build --samples data/decorative_samples/
```

### 3.6 过滤行为

命中装饰图后：
1. 文件从 `images/xxx.png` → 移到 `images/_filtered/xxx.png`（可恢复）
2. markdown 中对应 `![图N](images/xxx.png)` 引用被删除
3. 被删引用后的空行清理掉，保持格式整洁

### 3.7 日常使用流程

```bash
# 新发现一张装饰图时：
cp new_banner.png data/decorative_samples/banner_top/
python src/decorative_filter.py --build

# 下次下载文章时自动生效
```

## 4. 依赖

- `imagehash`：感知哈希计算
- `Pillow`：图片读取（项目未直接依赖但 imagehash 依赖它）

## 5. 边界情况

| 场景 | 处理 |
|------|------|
| 哈希库文件不存在 | 打印提示，跳过过滤（不阻断下载流程） |
| 图片下载失败（URL 模式） | 已在 image_map 中标记为失败，跳过 hash 计算 |
| `_filtered/` 中已有同名文件 | 覆盖（`os.rename` 会报错，加异常处理） |
| 汉明距离阈值恰好临界 | 默认 threshold=5，可在构建时调整 |

## 6. 不在范围内

- CNN 模型层（pHash 命中率足够时不需要）
- 按公众号分库（当前两个公众号同模板，同一份库即可）
- GUI 标记工具（命令行足够覆盖四五张图的场景）
