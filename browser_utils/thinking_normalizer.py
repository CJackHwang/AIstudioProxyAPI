"""
思考模式参数归一化模块
将 reasoning_effort 参数归一化为标准化的思考指令

本模块负责将各种格式的 reasoning_effort 参数转换为统一的内部指令结构。
"""

from typing import Optional, Any, Dict
from dataclasses import dataclass
from config import ENABLE_THINKING_BUDGET, DEFAULT_THINKING_BUDGET


@dataclass
class ThinkingDirective:
    """标准化的思考指令

    属性:
        thinking_enabled: 是否启用思考模式（总开关）
        budget_enabled: 是否限制思考预算
        budget_value: 预算token数量（仅当budget_enabled=True时有效）
        original_value: 原始的reasoning_effort值（用于日志）
    """
    thinking_enabled: bool
    budget_enabled: bool
    budget_value: Optional[int]
    original_value: Any


def normalize_reasoning_effort(reasoning_effort: Optional[Any]) -> ThinkingDirective:
    """将 reasoning_effort 参数归一化为标准化的思考指令

    参数:
        reasoning_effort: API请求中的reasoning_effort参数，可能的取值：
            - None: 使用默认配置
            - 0 或 "0": 关闭思考模式
            - 正整数: 开启思考，设置具体预算值
            - "low"/"medium"/"high": 开启思考，使用预设预算
            - "none"或"-1"或-1: 开启思考，不限制预算

    返回:
        ThinkingDirective: 标准化的思考指令

    示例:
        >>> normalize_reasoning_effort(None)
        ThinkingDirective(thinking_enabled=False, budget_enabled=False, budget_value=None, ...)

        >>> normalize_reasoning_effort(0)
        ThinkingDirective(thinking_enabled=False, budget_enabled=False, budget_value=None, ...)

        >>> normalize_reasoning_effort("medium")
        ThinkingDirective(thinking_enabled=True, budget_enabled=True, budget_value=8000, ...)

        >>> normalize_reasoning_effort("none")
        ThinkingDirective(thinking_enabled=True, budget_enabled=False, budget_value=None, ...)
    """

    # 场景1: 用户未指定，使用默认配置
    if reasoning_effort is None:
        return ThinkingDirective(
            thinking_enabled=ENABLE_THINKING_BUDGET,
            budget_enabled=ENABLE_THINKING_BUDGET,
            budget_value=DEFAULT_THINKING_BUDGET if ENABLE_THINKING_BUDGET else None,
            original_value=None
        )

    # 场景2: 关闭思考模式 (reasoning_effort = 0 或 "0")
    if reasoning_effort == 0 or (isinstance(reasoning_effort, str) and reasoning_effort.strip() == "0"):
        return ThinkingDirective(
            thinking_enabled=False,
            budget_enabled=False,
            budget_value=None,
            original_value=reasoning_effort
        )

    # 场景3: 开启思考但不限制预算 (reasoning_effort = "none" / "-1" / -1)
    if isinstance(reasoning_effort, str):
        reasoning_str = reasoning_effort.strip().lower()
        if reasoning_str in ["none", "-1"]:
            return ThinkingDirective(
                thinking_enabled=True,
                budget_enabled=False,
                budget_value=None,
                original_value=reasoning_effort
            )
    elif reasoning_effort == -1:
        return ThinkingDirective(
            thinking_enabled=True,
            budget_enabled=False,
            budget_value=None,
            original_value=reasoning_effort
        )

    # 场景4: 开启思考且限制预算 (具体数字或预设值)
    budget_value = _parse_budget_value(reasoning_effort)

    if budget_value is not None and budget_value > 0:
        return ThinkingDirective(
            thinking_enabled=True,
            budget_enabled=True,
            budget_value=budget_value,
            original_value=reasoning_effort
        )

    # 无效值：使用默认配置
    return ThinkingDirective(
        thinking_enabled=ENABLE_THINKING_BUDGET,
        budget_enabled=ENABLE_THINKING_BUDGET,
        budget_value=DEFAULT_THINKING_BUDGET if ENABLE_THINKING_BUDGET else None,
        original_value=reasoning_effort
    )


def _parse_budget_value(reasoning_effort: Any) -> Optional[int]:
    """解析预算值

    参数:
        reasoning_effort: reasoning_effort参数值

    返回:
        int: 预算token数量，如果无法解析则返回None
    """
    # 如果是整数，直接返回
    if isinstance(reasoning_effort, int) and reasoning_effort > 0:
        return reasoning_effort

    # 如果是字符串，尝试匹配预设值或解析为数字
    if isinstance(reasoning_effort, str):
        effort_str = reasoning_effort.strip().lower()

        # 预设值映射
        effort_map = {
            "low": 10923,
            "medium": 21845,
            "high": 32768,
        }

        # 先尝试预设值
        if effort_str in effort_map:
            return effort_map[effort_str]

        # 再尝试解析为数字
        try:
            value = int(effort_str)
            if value > 0:
                return value
        except (ValueError, TypeError):
            pass

    return None


def format_directive_log(directive: ThinkingDirective) -> str:
    """格式化思考指令为日志字符串

    参数:
        directive: 思考指令

    返回:
        str: 格式化的日志字符串
    """
    if not directive.thinking_enabled:
        return f"关闭思考模式 (原始值: {directive.original_value})"
    elif directive.budget_enabled and directive.budget_value is not None:
        return f"开启思考并限制预算: {directive.budget_value} tokens (原始值: {directive.original_value})"
    else:
        return f"开启思考，不限制预算 (原始值: {directive.original_value})"
