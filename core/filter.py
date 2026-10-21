# 兼容适配层，所有过滤核心逻辑迁移至 utils/text_filter.py
# 原有业务代码 from filter import is_valid_transcript 完全不用修改
from utils.text_filter import is_valid_transcript as core_check

# 保持旧接口：仅返回布尔值，和你原来调用逻辑一模一样
def is_valid_transcript(text: str) -> bool:
    valid_flag, _tip = core_check(text)
    return valid_flag

# 导出原有项目依赖的函数名
__all__ = ["is_valid_transcript"]