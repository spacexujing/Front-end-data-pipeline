"""
html_validator.py — HTML 有效性检测模块

对 HTML 代码进行多维度结构校验，判断其是否为正常、完整的 HTML 文档。

检测维度：
  1. 截断检测      — 文件是否在标签/字符串/属性中间突然结束
  2. 标签平衡      — 开放标签与闭合标签是否一一对应
  3. 嵌套合法性    — 块级元素是否错误嵌套在内联元素中
  4. 必要结构      — 是否包含 doctype / html / head / body 等基本结构
  5. 解析器容错    — html5lib 严格解析（如可用）；标准库 HTMLParser 兜底

Usage:
    from html_validator import validate_html, is_valid_html

    # 传入文件路径
    result = validate_html("result/0.html")
    print(result["is_valid"])   # True / False
    print(result["errors"])     # 具体错误列表

    # 传入 HTML 字符串
    result = validate_html(html_string)

    # 快速判断
    if is_valid_html("result/0.html"):
        print("OK")
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Union
from dataclasses import dataclass, field
from html.parser import HTMLParser
from collections import Counter


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ValidationError:
    """单个校验错误"""
    category: str           # "truncation" | "unclosed_tag" | "mismatched_tag" |
                            # "nesting" | "structure" | "parse_error"
    message: str            # 人类可读的描述
    location: str = ""      # 出错位置提示（如 "line ~480"、"near <div>"）
    severity: str = "error" # "error" | "warning"


@dataclass
class ValidationResult:
    """校验结果"""
    is_valid: bool                          # 是否为有效的 HTML
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)  # 统计信息


# ============================================================================
# 常量
# ============================================================================

# 自闭合标签（Void elements — 不需要闭合标签）
VOID_ELEMENTS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
}

# HTML 结构标签（浏览器会自动补全，缺少不一定是真正错误）
STRUCTURAL_TAGS = {'html', 'head', 'body'}

# 块级元素（不能嵌套在内联元素中）
BLOCK_ELEMENTS = {
    'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
    'section', 'article', 'aside', 'nav', 'header', 'footer', 'main',
    'figure', 'figcaption', 'blockquote', 'pre', 'hr',
    'form', 'fieldset', 'address', 'details', 'summary',
    'div', 'canvas', 'video', 'audio',
}

# 内联元素（不能包含块级元素）
INLINE_ELEMENTS = {
    'span', 'a', 'strong', 'em', 'b', 'i', 'u', 's', 'del', 'ins',
    'small', 'mark', 'sub', 'sup', 'code', 'kbd', 'samp', 'var',
    'abbr', 'cite', 'dfn', 'q', 'time', 'label', 'br', 'img',
    'input', 'select', 'textarea', 'button',
}

# 需要父元素为特定标签的元素
NESTING_RULES = {
    'li': {'ul', 'ol'},
    'dt': {'dl'}, 'dd': {'dl'},
    'thead': {'table'}, 'tbody': {'table'}, 'tfoot': {'table'},
    'tr': {'table', 'thead', 'tbody', 'tfoot'},
    'th': {'tr'}, 'td': {'tr'},
    'option': {'select', 'optgroup', 'datalist'},
    'optgroup': {'select'},
}


# ============================================================================
# 检测 1: 截断检测（纯文本分析）
# ============================================================================

def _check_truncation(html: str) -> List[ValidationError]:
    """
    检测 HTML 字符串是否在标签、属性、字符串或注释中间突然截断。

    此函数不依赖解析器，直接扫描原始字符。
    """
    errors: List[ValidationError] = []
    lines = html.split('\n')
    total_lines = len(lines)
    last_line = lines[-1] if lines else ''
    last_few = '\n'.join(lines[-3:]) if len(lines) >= 3 else html[-200:]

    # 1. 检测末尾是否在标签内部（有未闭合的 < 没有对应的 >）
    #    忽略已知的不需要 > 的场景
    tag_open_count = 0
    in_comment = False
    in_string = False
    string_char = ''

    i = 0
    while i < len(html):
        ch = html[i]

        if in_comment:
            if ch == '-' and i + 2 < len(html) and html[i:i+3] == '-->':
                in_comment = False
                i += 2
        elif in_string:
            if ch == '\\':
                i += 1  # 跳过转义字符
            elif ch == string_char:
                in_string = False
        else:
            if ch == '"' or ch == "'":
                # 检查是否在 <script> 或 <style> 内部，或标签属性内部
                # 简化处理：跟踪字符串状态
                in_string = True
                string_char = ch
            elif ch == '<':
                # 检查是否是注释开始
                if i + 3 < len(html) and html[i:i+4] == '<!--':
                    in_comment = True
                    i += 3
                elif i + 1 < len(html) and html[i+1] not in (' ', '\t', '\n', '/', '!', '?'):
                    # 标签开始
                    tag_open_count += 1
            elif ch == '>':
                tag_open_count -= 1

        i += 1

    # 检测末尾不完整的闭合标签（如 "...\n  </"）
    last_two_chars = html.strip()[-2:] if len(html.strip()) >= 2 else ''
    last_three = html.strip()[-3:] if len(html.strip()) >= 3 else ''
    if last_two_chars == '</' or last_three == '</':
        snippet = html.strip()[-60:].replace('\n', ' ')
        errors.append(ValidationError(
            category="truncation",
            message="HTML 在闭合标签中间截断（</ 后面缺少标签名和 >）",
            location=f"末尾: ...{snippet}",
            severity="error",
        ))

    # 最终状态检查
    if in_comment:
        errors.append(ValidationError(
            category="truncation",
            message="HTML 在注释中间截断（<!-- 没有对应的 -->）",
            location=f"末尾附近",
            severity="error",
        ))

    if in_string:
        errors.append(ValidationError(
            category="truncation",
            message=f"HTML 在字符串中间截断（引号未闭合）",
            location=f"末尾附近: ...{last_few[-50:]}",
            severity="error",
        ))

    if tag_open_count > 0:
        # 进一步确认：检查最后一个 < 的位置
        last_open = html.rfind('<')
        last_close = html.rfind('>')
        if last_open > last_close:
            # 提取最后一个不完整的标签
            snippet = html[last_open:last_open+60].replace('\n', ' ')
            errors.append(ValidationError(
                category="truncation",
                message=f"HTML 在标签中间截断（有 {tag_open_count} 个未闭合的 '<'）",
                location=f"最后一个不完整标签: {snippet}",
                severity="error",
            ))

    # 2. 检测末尾是否在 <script> 或 <style> 内部截断
    #    找最后一个 <script 或 <style 开始但没有对应的 </script> 或 </style>
    for tag_name in ('script', 'style'):
        # 用简单的方法：统计开始和结束标签的数量
        # 注意：需要处理 <script type="..."> 这样的情况
        open_pattern = re.compile(rf'<{tag_name}[\s>]', re.IGNORECASE)
        close_pattern = re.compile(rf'</{tag_name}\s*>', re.IGNORECASE)

        opens = len(open_pattern.findall(html))
        closes = len(close_pattern.findall(html))

        if opens > closes:
            # 找到最后一个 script/style 开始的位置
            last_start = -1
            for m in open_pattern.finditer(html):
                last_start = m.start()

            if last_start > 0:
                remaining = html[last_start:]
                # 如果剩余内容中没有闭合标签，就是截断了
                if not close_pattern.search(remaining):
                    snippet = remaining[:80].replace('\n', ' ')
                    errors.append(ValidationError(
                        category="truncation",
                        message=f"<{tag_name}> 标签内容在闭合前截断",
                        location=f"line ~{html[:last_start].count(chr(10)) + 1}: {snippet}",
                        severity="error",
                    ))

    return errors


# ============================================================================
# 检测 2: 标签平衡检测（使用 HTMLParser）
# ============================================================================

class _BalanceCheckingParser(HTMLParser):
    """跟踪标签打开/关闭，检测未闭合标签和标签不匹配。"""

    def __init__(self):
        super().__init__()
        self.tag_stack: List[str] = []          # 当前打开的标签
        self.unclosed_tags: List[str] = []       # 文件结束时仍未关闭的标签
        self.mismatches: List[Dict] = []          # 标签不匹配记录
        self.parse_errors: List[str] = []         # 解析异常消息
        self._void_elements = VOID_ELEMENTS

    def handle_starttag(self, tag: str, attrs):
        tag_lower = tag.lower()
        if tag_lower not in self._void_elements:
            self.tag_stack.append(tag_lower)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()

        if tag_lower in self._void_elements:
            # 自闭合标签不应有结束标签（如 </img>, </br>）
            self.mismatches.append({
                'type': 'void_with_endtag',
                'tag': tag_lower,
                'message': f'自闭合标签 <{tag_lower}> 不应有结束标签 </{tag_lower}>',
            })
            return

        # 在栈中查找匹配的开始标签
        if tag_lower in self.tag_stack:
            # 找到了，但需要检查中间是否有未闭合的标签
            # 从栈顶向下查找
            idx = len(self.tag_stack) - 1
            while idx >= 0 and self.tag_stack[idx] != tag_lower:
                idx -= 1

            if idx == len(self.tag_stack) - 1:
                # 正确的嵌套：栈顶就是匹配的标签
                self.tag_stack.pop()
            else:
                # 标签匹配但嵌套有问题（中间有标签未闭合）
                unclosed = self.tag_stack[idx + 1:]
                for tag in unclosed:
                    self.mismatches.append({
                        'type': 'implicit_close',
                        'tag': tag,
                        'message': f'<{tag}> 可能未正确闭合（在遇到 </{tag_lower}> 前）',
                    })
                # 移除匹配的标签及其后所有标签
                self.tag_stack = self.tag_stack[:idx]
        else:
            # 栈中没有对应的开始标签
            self.mismatches.append({
                'type': 'extra_endtag',
                'tag': tag_lower,
                'message': f'多余的闭合标签 </{tag_lower}>，未找到对应的开始标签',
            })

    def handle_startendtag(self, tag: str, attrs):
        # 自闭合标签（如 <br />, <meta />），不需要处理
        pass

    def error(self, message):
        """HTMLParser 的错误回调"""
        self.parse_errors.append(message)

    def finalize(self):
        """解析完成后，栈中剩余的标签就是未闭合的"""
        self.unclosed_tags = list(self.tag_stack)
        return self


def _check_tag_balance(html: str) -> List[ValidationError]:
    """使用 HTMLParser 检测标签平衡问题。"""
    errors: List[ValidationError] = []

    parser = _BalanceCheckingParser()
    try:
        parser.feed(html)
        parser.finalize()
    except Exception as e:
        errors.append(ValidationError(
            category="parse_error",
            message=f"HTMLParser 解析异常: {e}",
            location="",
            severity="error",
        ))
        # 解析器崩溃是最严重的错误，直接返回
        return errors

    # 收集解析错误
    for msg in parser.parse_errors:
        errors.append(ValidationError(
            category="parse_error",
            message=f"解析器报告: {msg}",
            severity="warning",
        ))

    # 未闭合标签 — 区分结构性标签和内容标签
    if parser.unclosed_tags:
        structural = [t for t in parser.unclosed_tags if t in STRUCTURAL_TAGS]
        content_tags = [t for t in parser.unclosed_tags if t not in STRUCTURAL_TAGS]

        if content_tags:
            tags_list = ', '.join(content_tags)
            errors.append(ValidationError(
                category="unclosed_tag",
                message=f"以下标签未闭合: {tags_list}",
                location=f"共 {len(content_tags)} 个标签缺少闭合标签",
                severity="error",
            ))
        if structural:
            tags_list = ', '.join(structural)
            errors.append(ValidationError(
                category="unclosed_tag",
                message=f"结构性标签未闭合: {tags_list}（浏览器可自动补全）",
                location=f"文件末尾",
                severity="warning",
            ))

    # 标签不匹配
    for mm in parser.mismatches:
        severity = "error" if mm['type'] == 'extra_endtag' else "warning"
        errors.append(ValidationError(
            category="mismatched_tag",
            message=mm['message'],
            location=f"标签: <{mm['tag']}>",
            severity=severity,
        ))

    return errors


# ============================================================================
# 检测 3: 嵌套合法性
# ============================================================================

class _NestingCheckingParser(HTMLParser):
    """检测块级元素是否错误嵌套在内联元素中，以及特定标签的父元素约束。"""

    def __init__(self):
        super().__init__()
        self.tag_stack: List[str] = []
        self.nesting_errors: List[Dict] = []
        self._void_elements = VOID_ELEMENTS

    def handle_starttag(self, tag: str, attrs):
        tag_lower = tag.lower()

        if tag_lower in self._void_elements:
            return

        # 检查：块级元素是否出现在内联元素内部
        if tag_lower in BLOCK_ELEMENTS:
            for parent_tag in reversed(self.tag_stack):
                if parent_tag in INLINE_ELEMENTS:
                    self.nesting_errors.append({
                        'type': 'block_in_inline',
                        'tag': tag_lower,
                        'parent': parent_tag,
                        'message': f'块级元素 <{tag_lower}> 不应嵌套在内联元素 <{parent_tag}> 内部',
                    })
                    break
                if parent_tag in BLOCK_ELEMENTS:
                    break  # 有块级祖先，合法

        # 检查：特定标签的父元素约束
        if tag_lower in NESTING_RULES:
            allowed_parents = NESTING_RULES[tag_lower]
            # 找最近的祖先
            parent_found = False
            for parent_tag in reversed(self.tag_stack):
                if parent_tag in allowed_parents:
                    parent_found = True
                    break
                if parent_tag in BLOCK_ELEMENTS or parent_tag in ('html', 'body', 'div'):
                    # 遇到了结构性的祖先但不是允许的父元素
                    break
            if not parent_found and self.tag_stack:
                self.nesting_errors.append({
                    'type': 'invalid_parent',
                    'tag': tag_lower,
                    'parent': self.tag_stack[-1],
                    'message': f'<{tag_lower}> 的父元素应为 {allowed_parents}，实际为 <{self.tag_stack[-1]}>',
                })

        self.tag_stack.append(tag_lower)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in self._void_elements:
            return

        if tag_lower in self.tag_stack:
            idx = len(self.tag_stack) - 1
            while idx >= 0 and self.tag_stack[idx] != tag_lower:
                idx -= 1
            if idx >= 0:
                self.tag_stack = self.tag_stack[:idx]

    def handle_startendtag(self, tag: str, attrs):
        pass


def _check_nesting(html: str) -> List[ValidationError]:
    """检测 HTML 元素嵌套是否合法。"""
    errors: List[ValidationError] = []

    parser = _NestingCheckingParser()
    try:
        parser.feed(html)
    except Exception as e:
        # 如果解析失败，嵌套检测的错误可能不完整
        errors.append(ValidationError(
            category="nesting",
            message=f"嵌套检测时解析失败: {e}",
            severity="warning",
        ))
        return errors

    for ne in parser.nesting_errors:
        errors.append(ValidationError(
            category="nesting",
            message=ne['message'],
            location=f"<{ne['tag']}> in <{ne['parent']}>",
            severity="warning",
        ))

    return errors


# ============================================================================
# 检测 4: 基本结构检查
# ============================================================================

def _check_structure(html: str) -> List[ValidationError]:
    """
    检测是否包含 HTML 文档的基本结构。

    注意：HTML5 规范下 doctype / html / head / body 都不是严格必须的，
    此处仅做建议性检查，标记为 warning。
    """
    errors: List[ValidationError] = []
    html_lower = html.lower()

    # doctype（HTML5 标准 doctype）
    if not re.search(r'<!DOCTYPE\s+html', html, re.IGNORECASE):
        errors.append(ValidationError(
            category="structure",
            message="缺少 DOCTYPE 声明（建议添加 <!DOCTYPE html>）",
            severity="warning",
        ))

    # <html> 标签
    if not re.search(r'<html[\s>]', html, re.IGNORECASE):
        errors.append(ValidationError(
            category="structure",
            message="缺少 <html> 标签",
            severity="warning",
        ))
    elif not re.search(r'</html\s*>', html, re.IGNORECASE):
        errors.append(ValidationError(
            category="structure",
            message="缺少 </html> 闭合标签（浏览器可自动补全）",
            severity="warning",
        ))

    # <head> 标签
    has_head_open = bool(re.search(r'<head[\s>]', html, re.IGNORECASE))
    has_head_close = bool(re.search(r'</head\s*>', html, re.IGNORECASE))
    if has_head_open and not has_head_close:
        errors.append(ValidationError(
            category="structure",
            message="<head> 标签未闭合",
            severity="warning",
        ))

    # <body> 标签
    has_body_open = bool(re.search(r'<body[\s>]', html, re.IGNORECASE))
    has_body_close = bool(re.search(r'</body\s*>', html, re.IGNORECASE))
    if has_body_open and not has_body_close:
        errors.append(ValidationError(
            category="structure",
            message="<body> 标签未闭合（浏览器可自动补全）",
            severity="warning",
        ))

    return errors


# ============================================================================
# 检测 5: html5lib 严格解析（可选）
# ============================================================================

def _check_with_html5lib(html: str) -> List[ValidationError]:
    """
    使用 html5lib 严格解析 HTML。

    html5lib 遵循 HTML5 规范的解析算法，比标准库 HTMLParser 更严格。
    如果未安装 html5lib，返回空列表（不算错误）。
    """
    errors: List[ValidationError] = []

    try:
        import html5lib
        from html5lib import html5parser
    except ImportError:
        return errors  # 未安装，跳过

    try:
        # 使用严格模式解析
        parser = html5lib.HTMLParser(strict=True)
        parser.parse(html)
    except Exception as e:
        errors.append(ValidationError(
            category="parse_error",
            message=f"html5lib 严格解析失败: {e}",
            severity="error",
        ))

    return errors


# ============================================================================
# 主函数
# ============================================================================

def validate_html(source: str, strict: bool = False) -> ValidationResult:
    """
    校验 HTML 代码或文件是否有效。

    Args:
        source: HTML 文件路径或 HTML 代码字符串。
                如果是已存在的文件路径 → 读取文件内容。
                否则 → 视为 HTML 字符串直接校验。
        strict: 是否启用严格模式（尝试 html5lib 解析）。

    Returns:
        ValidationResult，包含 is_valid、errors、warnings、stats。

    Examples:
        >>> result = validate_html("result/0.html")
        >>> print(result.is_valid)
        False
        >>> for e in result.errors:
        ...     print(f"[{e.category}] {e.message}")

        >>> result = validate_html("<html><body><p>Hello</p></body></html>")
        >>> print(result.is_valid)
        True
    """
    # ── 1. 读取输入 ──────────────────────────────────────────
    if os.path.isfile(source):
        filepath = source
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                html = f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            try:
                with open(filepath, 'r', encoding='gbk') as f:
                    html = f.read()
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    errors=[ValidationError(
                        category="parse_error",
                        message=f"无法读取文件（编码错误）: {e}",
                        severity="error",
                    )],
                )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[ValidationError(
                    category="parse_error",
                    message=f"无法读取文件: {e}",
                    severity="error",
                )],
            )
        source_label = os.path.basename(filepath)
    else:
        html = source
        source_label = "<string>"

    # 空内容检查
    if not html or not html.strip():
        return ValidationResult(
            is_valid=False,
            errors=[ValidationError(
                category="structure",
                message="HTML 内容为空",
                severity="error",
            )],
            stats={'source': source_label, 'size': 0, 'lines': 0},
        )

    lines = html.count('\n') + 1

    # ── 2. 执行各项检测 ──────────────────────────────────────
    all_errors: List[ValidationError] = []
    all_warnings: List[ValidationError] = []

    # 2a. 截断检测（最先做，因为截断的 HTML 会导致后续检测不准）
    truncation_errors = _check_truncation(html)
    all_errors.extend(truncation_errors)

    # 2b. 标签平衡检测
    balance_issues = _check_tag_balance(html)
    for e in balance_issues:
        if e.severity == "error":
            all_errors.append(e)
        else:
            all_warnings.append(e)

    # 2c. 嵌套合法性
    nesting_issues = _check_nesting(html)
    for e in nesting_issues:
        if e.severity == "error":
            all_errors.append(e)
        else:
            all_warnings.append(e)

    # 2d. 基本结构检查
    structure_issues = _check_structure(html)
    for e in structure_issues:
        if e.severity == "error":
            all_errors.append(e)
        else:
            all_warnings.append(e)

    # 2e. html5lib 严格解析（如果启用且有安装）
    if strict:
        html5lib_errors = _check_with_html5lib(html)
        all_errors.extend(html5lib_errors)

    # ── 3. 汇总结果 ──────────────────────────────────────────
    # 去重（按 message 去重）
    seen = set()
    unique_errors = []
    for e in all_errors:
        key = (e.category, e.message)
        if key not in seen:
            seen.add(key)
            unique_errors.append(e)

    unique_warnings = []
    for w in all_warnings:
        key = (w.category, w.message)
        if key not in seen:
            seen.add(key)
            unique_warnings.append(w)

    is_valid = len(unique_errors) == 0

    stats = {
        'source': source_label,
        'size': len(html),
        'size_kb': round(len(html) / 1024, 1),
        'lines': lines,
        'error_count': len(unique_errors),
        'warning_count': len(unique_warnings),
        'checks_performed': ['truncation', 'tag_balance', 'nesting', 'structure']
                          + (['html5lib'] if strict else []),
    }

    return ValidationResult(
        is_valid=is_valid,
        errors=unique_errors,
        warnings=unique_warnings,
        stats=stats,
    )


def is_valid_html(source: str, strict: bool = False) -> bool:
    """
    快速判断 HTML 是否有效。

    Args:
        source: HTML 文件路径或 HTML 字符串。
        strict: 是否启用严格模式。

    Returns:
        True 如果 HTML 有效（没有 error 级别的校验问题）。
    """
    result = validate_html(source, strict=strict)
    return result.is_valid


def batch_validate(
    file_paths: List[str],
    strict: bool = False,
    show_progress: bool = True,
) -> Dict[str, ValidationResult]:
    """
    批量校验多个 HTML 文件。

    Args:
        file_paths: HTML 文件路径列表。
        strict: 是否启用严格模式。
        show_progress: 是否打印进度。

    Returns:
        {filepath: ValidationResult} 字典。
    """
    results: Dict[str, ValidationResult] = {}
    total = len(file_paths)

    for i, fp in enumerate(file_paths):
        if show_progress:
            print(f"[{i+1}/{total}] Checking: {os.path.basename(fp)} ...", end=' ')

        result = validate_html(fp, strict=strict)
        results[fp] = result

        if show_progress:
            status = "✓ OK" if result.is_valid else f"✗ {result.stats['error_count']} error(s)"
            print(status)

    return results


# ============================================================================
# 格式化输出
# ============================================================================

def print_result(result: ValidationResult, verbose: bool = False) -> None:
    """美观地打印校验结果。"""
    stats = result.stats

    # 状态行
    if result.is_valid:
        print(f"\n✅ 有效 HTML — {stats.get('source', '?')}")
    else:
        print(f"\n❌ 无效 HTML — {stats.get('source', '?')}")

    print(f"   大小: {stats.get('size_kb', '?')} KB | "
          f"行数: {stats.get('lines', '?')} | "
          f"错误: {stats.get('error_count', 0)} | "
          f"警告: {stats.get('warning_count', 0)}")

    # 错误详情
    if result.errors:
        print(f"\n  ▸ 错误 ({len(result.errors)}):")
        for e in result.errors:
            print(f"    [{e.category}] {e.message}")
            if verbose and e.location:
                print(f"       位置: {e.location}")

    # 警告详情（仅在 verbose 模式下）
    if verbose and result.warnings:
        print(f"\n  ▸ 警告 ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    [{w.category}] {w.message}")
            if w.location:
                print(f"       位置: {w.location}")


# ============================================================================
# CLI
# ============================================================================

if __name__ == '__main__':
    import sys

    # 强制 UTF-8 输出
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    if len(sys.argv) < 2:
        print("HTML 有效性检测工具")
        print()
        print("Usage:")
        print("  python html_validator.py <file.html>        校验单个文件")
        print("  python html_validator.py <file.html> -v     详细模式")
        print("  python html_validator.py <file.html> --strict  严格模式（html5lib）")
        print("  python html_validator.py --batch <dir>       批量校验目录下所有 HTML 文件")
        print("  python html_validator.py --inline '<html>'   直接校验 HTML 字符串")
        print()
        print("也可以在 Python 代码中导入使用:")
        print("  from html_validator import validate_html, is_valid_html")
        print("  result = validate_html('page.html')")
        print("  print(result.is_valid)")
        sys.exit(1)

    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    strict = '--strict' in sys.argv

    # 批量模式
    if '--batch' in sys.argv:
        idx = sys.argv.index('--batch')
        if idx + 1 < len(sys.argv):
            target_dir = sys.argv[idx + 1]
        else:
            target_dir = '.'

        html_files = []
        for root, dirs, files in os.walk(target_dir):
            for f in files:
                if f.endswith('.html') or f.endswith('.htm'):
                    html_files.append(os.path.join(root, f))

        if not html_files:
            print(f"在 {target_dir} 中未找到 HTML 文件")
            sys.exit(0)

        print(f"找到 {len(html_files)} 个 HTML 文件\n")
        results = batch_validate(html_files, strict=strict, show_progress=True)

        # 汇总
        valid_count = sum(1 for r in results.values() if r.is_valid)
        invalid_count = len(results) - valid_count
        print(f"\n{'='*50}")
        print(f"  总计: {len(results)} | 有效: {valid_count} | 无效: {invalid_count}")

        if invalid_count > 0:
            print(f"\n  无效文件:")
            for fp, r in results.items():
                if not r.is_valid:
                    error_types = Counter(e.category for e in r.errors)
                    print(f"    ✗ {os.path.basename(fp)} — {', '.join(f'{k}({v})' for k, v in error_types.items())}")

        if verbose:
            for fp, r in results.items():
                if not r.is_valid:
                    print_result(r, verbose=True)

        sys.exit(0 if invalid_count == 0 else 1)

    # 内联模式
    if '--inline' in sys.argv:
        idx = sys.argv.index('--inline')
        if idx + 1 < len(sys.argv):
            html_content = sys.argv[idx + 1]
        else:
            print("错误: --inline 需要提供 HTML 字符串")
            sys.exit(1)
        result = validate_html(html_content, strict=strict)
        print_result(result, verbose=verbose)
        sys.exit(0 if result.is_valid else 1)

    # 单文件模式
    filepath = sys.argv[1]
    if not os.path.isfile(filepath):
        print(f"错误: 文件不存在 — {filepath}")
        sys.exit(1)

    result = validate_html(filepath, strict=strict)
    print_result(result, verbose=verbose)
    sys.exit(0 if result.is_valid else 1)
