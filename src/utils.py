"""
共享工具模块
============
抽取自 translator.py / converter.py / downloader.py / oss_uploader.py /
github_uploader.py 中重复的逻辑，避免多处维护：

- resolve_llm_config      LLM 提供商配置解析（新旧格式兼容）
- clean_llm_response      清理 LLM 返回内容的代码块包裹
- find_file_by_suffix     在目录中按后缀查找文件
- find_file_by_basename   在目录中按 basename + 多扩展名查找文件
"""

import os
from typing import Optional


# 图片文件常见扩展名（按优先级排序）
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp']


def resolve_llm_config(config: dict, llm_name: str = None) -> dict:
    """
    解析 LLM 配置，支持新旧两种格式。

    新格式（多提供商）:
        llm:
          default: "qwen"
          providers:
            qwen: {api_key, base_url, model_name}
            deepseek: {api_key, base_url, model_name}

    旧格式（单提供商，向后兼容）:
        llm:
          api_key: "..."
          base_url: "..."
          model_name: "..."

    参数:
        config:   完整的 config.yaml 字典
        llm_name: 指定提供商名称，不传则用 llm.default

    返回:
        {'name', 'api_key', 'base_url', 'model_name', ...} 字典

    异常:
        ValueError: 未配置任何提供商，或指定的提供商不存在
    """
    llm_cfg = config.get('llm', {})

    # 旧格式：llm 下直接有 api_key
    if 'api_key' in llm_cfg:
        return {
            'name': 'default',
            'api_key': llm_cfg['api_key'],
            'base_url': llm_cfg.get('base_url', ''),
            'model_name': llm_cfg.get('model_name', ''),
        }

    # 新格式：llm.providers
    providers = llm_cfg.get('providers', {})
    if not providers:
        raise ValueError("config.yaml 中未配置任何 LLM 提供商")

    # 选择提供商
    name = llm_name or llm_cfg.get('default')
    if name not in providers:
        available = ', '.join(providers.keys())
        raise ValueError(
            f"LLM 提供商 '{name}' 未在 config.yaml 中配置。"
            f" 可用: {available}"
        )

    provider = providers[name].copy()
    provider['name'] = name
    return provider


def clean_llm_response(content: str) -> str:
    """
    去除 LLM 返回内容可能包裹的代码块标记。

    覆盖所有常见包裹格式：```json / ```yaml / ```markdown / ```，
    清除首部标记和尾部 ```。
    """
    content = content.strip()
    for prefix in ('```json', '```yaml', '```markdown', '```'):
        if content.startswith(prefix):
            content = content[len(prefix):]
            break
    if content.endswith('```'):
        content = content[:-3]
    return content.strip()


def find_file_by_suffix(directory: str, suffix: str) -> Optional[str]:
    """在目录中查找第一个以 suffix 结尾的文件，返回完整路径。"""
    if not os.path.isdir(directory):
        return None
    for name in os.listdir(directory):
        if name.endswith(suffix):
            return os.path.join(directory, name)
    return None


def find_file_by_basename(directory: str, basename: str,
                          extensions=None) -> Optional[str]:
    """
    在目录中按 basename（不含扩展名）+ 多个扩展名查找文件。

    参数:
        directory:  目标目录
        basename:   文件名主体（如 "img_001" / "pic1"）
        extensions: 扩展名列表，默认使用 IMAGE_EXTENSIONS
    """
    if extensions is None:
        extensions = IMAGE_EXTENSIONS
    for ext in extensions:
        fpath = os.path.join(directory, f'{basename}{ext}')
        if os.path.exists(fpath):
            return fpath
    return None
