"""
rule_code — 前端美学质量：规则化代码判定模块

对 HTML 代码进行静态分析，输出 12 个维度中可规则化判定的评分。
所有判定均基于确定性规则（WCAG 公式、DOM 解析、CSS 属性提取等），不依赖 AI/LLM。

Usage:
    from rule_code import evaluate_all
    results = evaluate_all(html_string)
    print(results['overall_score'])
"""

from .rule_code import evaluate_all, DimensionResult, Issue

__all__ = ['evaluate_all', 'DimensionResult', 'Issue']
