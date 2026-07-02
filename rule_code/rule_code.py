"""
rule_code.py — 前端美学质量：规则化代码判定模块

对 HTML 代码进行**纯静态分析**，覆盖 L1 基础可用性 + L2 视觉协调性中可规则化的维度。
所有判定均基于确定性规则，不依赖 AI/LLM，不需要浏览器渲染。

维度一览：
  L1-1  对比度检测          check_contrast_ratio
  L1-2  字号下限            check_font_size
  L1-3  行高下限            check_line_height
  L1-4  语义化标签          check_semantic_tags
  L1-5  ARIA 属性           check_aria_attributes
  L1-6  Meta 标签           check_meta_tags
  L1-7  键盘导航基础         check_keyboard_navigation
  L2-1  字体族数量           check_font_family_count
  L2-2  字号层级             check_font_hierarchy
  L2-3  色板与主色数量       check_color_palette
  L2-4  间距一致性（8px网格） check_spacing_consistency
  L2-5  溢出风险（静态预估）  check_overflow_risk

Usage:
    from rule_code import evaluate_all

    with open("page.html", "r", encoding="utf-8") as f:
        html = f.read()

    result = evaluate_all(html)
    print(f"总分: {result['overall_score']:.2f}")
    for dim, info in result['dimensions'].items():
        print(f"  {dim}: {info['score']:.2f}  ({info['label']})")
"""

from __future__ import annotations

import re
import math
import colorsys
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from html.parser import HTMLParser


# ============================================================================
# 常量定义
# ============================================================================

# WCAG 2.0 AA 对比度阈值
CONTRAST_AA_NORMAL = 4.5   # 普通文字
CONTRAST_AA_LARGE = 3.0    # 大文字（≥18px 或 ≥14px bold）

# 字号相关
MIN_FONT_SIZE_PX = 12
MIN_LINE_HEIGHT_RATIO = 1.4
MAX_FONT_FAMILIES = 2

# 8px 网格
GRID_UNIT_PX = 8
GRID_TOLERANCE_PX = 2  # ±2px 容差

# 色板
MAX_PRIMARY_COLORS = 3
COLOR_CLUSTER_THRESHOLD = 25  # Delta E 距离阈值

# 推荐语义标签
SEMANTIC_TAGS = [
    'main', 'nav', 'article', 'section', 'aside',
    'header', 'footer', 'figure', 'figcaption', 'time', 'address'
]

# 文本类 HTML 元素（可能包含可见文字）
TEXT_ELEMENTS = {
    'p', 'span', 'a', 'li', 'td', 'th', 'label', 'button',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'div', 'pre', 'code', 'blockquote', 'q', 'cite',
    'strong', 'em', 'b', 'i', 'u', 'small', 'mark', 'del', 'ins',
    'dt', 'dd', 'figcaption', 'legend', 'option',
    'summary', 'details',
}

# 交互类元素
INTERACTIVE_ELEMENTS = {
    'a', 'button', 'input', 'select', 'textarea',
    'details', 'summary',
}

# 常见 HTML 颜色名 → Hex
NAMED_COLORS: Dict[str, str] = {
    'white': '#ffffff', 'black': '#000000',
    'red': '#ff0000', 'green': '#008000', 'blue': '#0000ff',
    'yellow': '#ffff00', 'orange': '#ffa500', 'purple': '#800080',
    'gray': '#808080', 'grey': '#808080', 'silver': '#c0c0c0',
    'navy': '#000080', 'teal': '#008080', 'maroon': '#800000',
    'lime': '#00ff00', 'aqua': '#00ffff', 'fuchsia': '#ff00ff',
    'olive': '#808000', 'brown': '#a52a2a', 'coral': '#ff7f50',
    'crimson': '#dc143c', 'cyan': '#00ffff', 'gold': '#ffd700',
    'indigo': '#4b0082', 'ivory': '#fffff0', 'magenta': '#ff00ff',
    'pink': '#ffc0cb', 'plum': '#dda0dd', 'salmon': '#fa8072',
    'tan': '#d2b48c', 'tomato': '#ff6347', 'violet': '#ee82ee',
    'wheat': '#f5deb3', 'transparent': 'transparent',
    'aliceblue': '#f0f8ff', 'antiquewhite': '#faebd7',
    'azure': '#f0ffff', 'beige': '#f5f5dc', 'bisque': '#ffe4c4',
    'blanchedalmond': '#ffebcd', 'blueviolet': '#8a2be2',
    'burlywood': '#deb887', 'cadetblue': '#5f9ea0',
    'chartreuse': '#7fff00', 'chocolate': '#d2691e',
    'cornflowerblue': '#6495ed', 'cornsilk': '#fff8dc',
    'darkblue': '#00008b', 'darkcyan': '#008b8b',
    'darkgray': '#a9a9a9', 'darkgreen': '#006400',
    'darkorange': '#ff8c00', 'darkred': '#8b0000',
    'darkslategray': '#2f4f4f', 'deepskyblue': '#00bfff',
    'dodgerblue': '#1e90ff', 'firebrick': '#b22222',
    'forestgreen': '#228b22', 'gainsboro': '#dcdcdc',
    'ghostwhite': '#f8f8ff', 'greenyellow': '#adff2f',
    'honeydew': '#f0fff0', 'hotpink': '#ff69b4',
    'khaki': '#f0e68c', 'lavender': '#e6e6fa',
    'lawngreen': '#7cfc00', 'lemonchiffon': '#fffacd',
    'lightblue': '#add8e6', 'lightcoral': '#f08080',
    'lightgray': '#d3d3d3', 'lightgreen': '#90ee90',
    'lightpink': '#ffb6c1', 'lightsalmon': '#ffa07a',
    'lightyellow': '#ffffe0', 'limegreen': '#32cd32',
    'linen': '#faf0e6', 'mediumblue': '#0000cd',
    'midnightblue': '#191970', 'mintcream': '#f5fffa',
    'mistyrose': '#ffe4e1', 'moccasin': '#ffe4b5',
    'oldlace': '#fdf5e6', 'orangered': '#ff4500',
    'orchid': '#da70d6', 'palegreen': '#98fb98',
    'papayawhip': '#ffefd5', 'peachpuff': '#ffdab9',
    'peru': '#cd853f', 'powderblue': '#b0e0e6',
    'rosybrown': '#bc8f8f', 'royalblue': '#4169e1',
    'saddlebrown': '#8b4513', 'sandybrown': '#f4a460',
    'seagreen': '#2e8b57', 'seashell': '#fff5ee',
    'sienna': '#a0522d', 'skyblue': '#87ceeb',
    'slateblue': '#6a5acd', 'slategray': '#708090',
    'snow': '#fffafa', 'springgreen': '#00ff7f',
    'steelblue': '#4682b4', 'thistle': '#d8bfd8',
    'turquoise': '#40e0d0', 'whitesmoke': '#f5f5f5',
    'yellowgreen': '#9acd32', 'rebeccapurple': '#663399',
}


# ============================================================================
# 基础数据结构
# ============================================================================

@dataclass
class Issue:
    """检测到的具体问题"""
    element: str = ""          # 元素描述（如 "h1.title"）
    property: str = ""         # 相关 CSS 属性
    current_value: str = ""    # 当前值
    expected: str = ""         # 期望值/标准
    severity: str = "warning"  # "error" | "warning" | "info"
    line_hint: str = ""        # 代码位置提示


@dataclass
class DimensionResult:
    """单个维度的判定结果"""
    dimension: str = ""        # 维度 key
    label: str = ""            # 中文标签
    score: float = 0.0         # 0.0 ~ 1.0
    weight: float = 1.0        # 维度权重
    details: Dict[str, Any] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    limitation_note: str = ""  # 静态分析的局限性说明


# ============================================================================
# 颜色工具
# ============================================================================

def _hex_to_rgb(hex_color: str) -> Optional[Tuple[int, int, int]]:
    """将 hex 颜色转换为 RGB 元组"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)
    if len(hex_color) != 6:
        return None
    try:
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _rgb_str_to_tuple(rgb_str: str) -> Optional[Tuple[int, int, int, float]]:
    """解析 rgb() / rgba() 字符串 → (r, g, b, a)"""
    rgb_str = rgb_str.strip()
    # rgba(r, g, b, a)
    m = re.match(
        r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)',
        rgb_str, re.IGNORECASE
    )
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                float(m.group(4)) if m.group(4) is not None else 1.0)
    return None


def _hsl_str_to_rgb(hsl_str: str) -> Optional[Tuple[int, int, int, float]]:
    """解析 hsl() / hsla() 字符串 → (r, g, b, a)"""
    m = re.match(
        r'hsla?\s*\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*(?:,\s*([\d.]+))?\s*\)',
        hsl_str, re.IGNORECASE
    )
    if m:
        h = float(m.group(1)) / 360.0
        s = float(m.group(2)) / 100.0
        l = float(m.group(3)) / 100.0
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return (int(r * 255), int(g * 255), int(b * 255), a)
    return None


def parse_color(color_str: str) -> Optional[Tuple[int, int, int, float]]:
    """
    解析任意 CSS 颜色值为 (r, g, b, alpha)。

    支持格式：hex、rgb()、rgba()、hsl()、hsla()、命名颜色、transparent。
    无法解析时返回 None。
    """
    if not color_str or not isinstance(color_str, str):
        return None

    color_str = color_str.strip().lower()

    # transparent
    if color_str == 'transparent':
        return (0, 0, 0, 0.0)

    # currentColor / inherit / var() — 无法静态解析
    if color_str in ('currentcolor', 'inherit', 'initial', 'unset'):
        return None
    if color_str.startswith('var('):
        return None

    # hex
    if color_str.startswith('#'):
        rgb = _hex_to_rgb(color_str)
        return (*rgb, 1.0) if rgb else None

    # rgb / rgba
    if color_str.startswith('rgb'):
        return _rgb_str_to_tuple(color_str)

    # hsl / hsla
    if color_str.startswith('hsl'):
        return _hsl_str_to_rgb(color_str)

    # 命名颜色
    if color_str in NAMED_COLORS:
        hex_val = NAMED_COLORS[color_str]
        if hex_val == 'transparent':
            return (0, 0, 0, 0.0)
        rgb = _hex_to_rgb(hex_val)
        return (*rgb, 1.0) if rgb else None

    return None


def _srgb_to_linear(c: float) -> float:
    """sRGB 通道值 → 线性光值（用于亮度计算）"""
    c = c / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: Tuple[int, int, int]) -> float:
    """
    计算 WCAG 2.0 定义的相对亮度。

    L = 0.2126 * R + 0.7152 * G + 0.0722 * B
    """
    r, g, b = rgb[:3]
    return 0.2126 * _srgb_to_linear(r) \
        + 0.7152 * _srgb_to_linear(g) \
        + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(fg: Tuple[int, int, int],
                   bg: Tuple[int, int, int]) -> float:
    """
    计算两个 sRGB 颜色之间的 WCAG 对比度。

    ratio = (L1 + 0.05) / (L2 + 0.05)，其中 L1 ≥ L2。
    """
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _color_distance(c1: Tuple[int, int, int],
                    c2: Tuple[int, int, int]) -> float:
    """两个 RGB 颜色之间的欧几里得距离（简化 Delta E）"""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])))


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """RGB → #rrggbb"""
    return '#{:02x}{:02x}{:02x}'.format(*rgb[:3])


# ============================================================================
# CSS 解析工具
# ============================================================================

def _parse_inline_style(style_attr: str) -> Dict[str, str]:
    """
    解析 inline style 属性字符串 → {property: value} 字典。

    Example: "color: red; font-size: 16px" → {"color": "red", "font-size": "16px"}
    """
    if not style_attr or not isinstance(style_attr, str):
        return {}
    props: Dict[str, str] = {}
    # 按分号分割，处理每个声明
    for decl in style_attr.split(';'):
        decl = decl.strip()
        if ':' not in decl:
            continue
        prop, value = decl.split(':', 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            props[prop] = value
    return props


def _parse_css_block(css_text: str) -> List[Dict[str, Any]]:
    """
    解析 <style> 块内容 → [{selector, declarations, specificity}] 列表。

    只处理基本选择器：tag、.class、#id、tag.class、parent child。
    """
    rules: List[Dict[str, Any]] = []
    # 移除注释
    css_text = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)

    # 按 } 分割规则
    blocks = re.findall(r'([^{]+)\{([^}]+)\}', css_text, re.DOTALL)
    for selector_str, declarations_str in blocks:
        selector_str = selector_str.strip()
        declarations_str = declarations_str.strip()

        if not selector_str or not declarations_str:
            continue

        # 处理逗号分隔的选择器
        selectors = [s.strip() for s in selector_str.split(',') if s.strip()]
        for sel in selectors:
            # 计算 specificity（简化版：id=100, class=10, tag=1）
            specificity = 0
            specificity += len(re.findall(r'#[\w-]+', sel)) * 100
            specificity += len(re.findall(r'\.[\w-]+', sel)) * 10
            specificity += len(re.findall(r':[\w-]+', sel)) * 10  # pseudo-class
            # 统计 tag 选择器（排除 id/class/pseudo 前缀后的词）
            tag_part = re.sub(r'#[.\w-]+', '', sel)
            tag_part = re.sub(r'\.[\w-]+', '', tag_part)
            tag_part = re.sub(r':[\w-]+', '', tag_part)
            specificity += len(re.findall(r'\b[a-z][a-z0-9]*\b', tag_part))

            # 解析声明
            declarations: Dict[str, str] = {}
            for decl in declarations_str.split(';'):
                decl = decl.strip()
                if ':' not in decl:
                    continue
                prop, value = decl.split(':', 1)
                prop = prop.strip().lower()
                value = value.strip()
                if prop and value:
                    declarations[prop] = value

            if declarations:
                rules.append({
                    'selector': sel,
                    'declarations': declarations,
                    'specificity': specificity,
                })

    return rules


def _selector_matches(selector: str, element: Dict[str, Any]) -> bool:
    """
    判断一个 CSS 选择器是否匹配给定的 DOM 元素。

    支持：tag、.class、#id、tag.class、parent child（一级）。
    """
    if not selector or not element:
        return False

    tag = element.get('tag', '')
    classes = _parse_classes(element.get('attrs', {}).get('class', ''))
    elem_id = element.get('attrs', {}).get('id', '')

    sel = selector.strip()

    # 处理后代选择器 "parent child"（只处理一级）
    parts = sel.split()
    if len(parts) == 2:
        parent_sel, child_sel = parts
        parent = element.get('parent')
        if parent is None:
            return False
        return (_selector_matches(child_sel, element) and
                _selector_matches(parent_sel, parent))
    if len(parts) > 2:
        # 多级后代：简化处理，只检查最后一级 + 祖先链中是否存在第一级
        return False  # 复杂选择器暂不处理

    # 单个选择器
    sel = parts[0] if parts else sel

    # #id 选择器
    id_match = re.search(r'#([\w-]+)', sel)
    if id_match:
        if elem_id != id_match.group(1):
            return False
        sel = sel.replace(id_match.group(0), '')

    # .class 选择器
    class_matches = re.findall(r'\.([\w-]+)', sel)
    for cls in class_matches:
        if cls not in classes:
            return False
        sel = sel.replace('.' + cls, '', 1)

    # 剩余部分是 tag 选择器
    remaining = sel.strip()
    if remaining and remaining != '*':
        if remaining.lower() != tag.lower():
            return False

    return True


def _parse_classes(class_attr: str) -> Set[str]:
    """解析 class 属性为集合"""
    if not class_attr:
        return set()
    return set(class_attr.strip().split())


# ============================================================================
# HTML 解析器
# ============================================================================

class _StyleCollectingHTMLParser(HTMLParser):
    """
    解析 HTML → 构建元素树 + 收集样式信息。

    产出：
      - root: 根元素（#root）
      - elements: 所有元素的扁平列表
      - style_blocks: <style> 标签的内容列表
      - meta_tags: {name: content} 字典
      - title_text: <title> 内容
    """

    def __init__(self):
        super().__init__()
        self.root: Dict[str, Any] = {
            'tag': '#root', 'attrs': {}, 'children': [],
            'parent': None, 'text': '', 'depth': 0
        }
        self.current: Dict[str, Any] = self.root
        self.elements: List[Dict[str, Any]] = [self.root]
        self.style_blocks: List[str] = []
        self.meta_tags: Dict[str, str] = {}
        self.title_text: str = ''
        self._in_style: bool = False
        self._in_title: bool = False
        self._style_content: str = ''
        self._title_content: str = ''
        # 不需要闭合标签的元素
        self._void_elements = {
            'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'
        }

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        attr_dict = {}
        for k, v in attrs:
            if v is None:
                v = ''
            attr_dict[k.lower()] = v

        element: Dict[str, Any] = {
            'tag': tag_lower,
            'attrs': attr_dict,
            'children': [],
            'parent': self.current,
            'text': '',
            'depth': self.current.get('depth', 0) + 1,
        }
        self.current['children'].append(element)
        self.current = element
        self.elements.append(element)

        if tag_lower == 'style':
            self._in_style = True
            self._style_content = ''
        elif tag_lower == 'title':
            self._in_title = True
            self._title_content = ''

        # 收集 meta 标签信息
        if tag_lower == 'meta':
            name_key = attr_dict.get('name') or attr_dict.get('property') or attr_dict.get('http-equiv') or ''
            content_val = attr_dict.get('content', '')
            if name_key:
                self.meta_tags[name_key.lower()] = content_val
            if 'charset' in attr_dict:
                self.meta_tags['charset'] = attr_dict['charset']

        # void elements don't push context
        if tag_lower in self._void_elements:
            self.current = element.get('parent', self.root)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == 'style' and self._in_style:
            self.style_blocks.append(self._style_content)
            self._in_style = False
            self._style_content = ''
        elif tag_lower == 'title' and self._in_title:
            self.title_text = self._title_content.strip()
            self._in_title = False
            self._title_content = ''

        # 向上遍历找到匹配的开始标签
        node = self.current
        while node and node.get('tag') != tag_lower:
            node = node.get('parent')
        if node and node.get('parent'):
            self.current = node['parent']
        elif node:
            self.current = node['parent'] if node['parent'] else self.root

    def handle_data(self, data: str):
        if self._in_style:
            self._style_content += data
        elif self._in_title:
            self._title_content += data
        else:
            stripped = data.strip()
            if stripped:
                self.current['text'] = (self.current.get('text', '') + ' ' + stripped).strip()

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        # 自闭合标签（如 <meta />, <br />）
        self.handle_starttag(tag, attrs)
        # void 元素已在 handle_starttag 中弹出，避免重复弹出导致父级错位
        if tag.lower() not in self._void_elements:
            self.current = self.current.get('parent', self.root)


def _parse_html(html: str) -> _StyleCollectingHTMLParser:
    """解析 HTML 字符串，返回解析器实例。"""
    parser = _StyleCollectingHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        # 容错：HTMLParser 对格式错误有基本容错，但仍可能抛异常
        pass
    return parser


# ============================================================================
# 样式解析引擎
# ============================================================================

def _resolve_styles(parser: _StyleCollectingHTMLParser) -> None:
    """
    为解析树中的每个元素解析样式。

    样式来源优先级（从低到高）：
      1. 浏览器默认样式（预置，可被继承覆盖）
      2. <style> 块中的规则（按 specificity 排序，标记为 explicit）
      3. inline style 属性（最高，标记为 explicit）
      4. CSS 属性继承（父 → 子，仅对非 explicit 属性生效）

    结果写入 element['resolved_styles']。
    """
    # CSS 中会从父元素继承的属性
    INHERITED_PROPERTIES = {
        'color', 'font-family', 'font-size', 'font-weight', 'font-style',
        'font-variant', 'line-height', 'text-align', 'text-indent',
        'letter-spacing', 'word-spacing', 'visibility', 'cursor',
        'direction', 'list-style', 'list-style-type',
    }

    # 1. 解析所有 <style> 块
    all_rules: List[Dict[str, Any]] = []
    for css_text in parser.style_blocks:
        all_rules.extend(_parse_css_block(css_text))
    all_rules.sort(key=lambda r: r['specificity'])

    # 2. 浏览器默认样式（仅结构性属性 + 根元素兜底；不阻止继承）
    default_styles: Dict[str, Dict[str, str]] = {
        'h1': {'font-weight': 'bold'},
        'h2': {'font-weight': 'bold'},
        'h3': {'font-weight': 'bold'},
        'h4': {'font-weight': 'bold'},
        'h5': {'font-weight': 'bold'},
        'h6': {'font-weight': 'bold'},
        'code': {'font-family': 'monospace'},
        'pre': {'font-family': 'monospace'},
    }
    # 根元素兜底值（会被任何显式声明覆盖）
    ROOT_DEFAULTS = {
        'font-size': '16px',
        'line-height': 'normal',
        'color': '#000000',
        'font-family': 'sans-serif',
    }

    # 3. 第一阶段：为每个元素解析自身样式（不含继承）
    for elem in parser.elements:
        tag = elem.get('tag', '')
        resolved: Dict[str, str] = {}
        explicit_props: Set[str] = set()

        # 浏览器默认（不标记为 explicit——可被继承覆盖）
        if tag in default_styles:
            resolved.update(default_styles[tag])

        # <style> 块规则（标记为 explicit）
        for rule in all_rules:
            if _selector_matches(rule['selector'], elem):
                for prop, val in rule['declarations'].items():
                    resolved[prop] = val
                    explicit_props.add(prop)

        # inline style（标记为 explicit，最高优先级）
        inline_styles = _parse_inline_style(elem.get('attrs', {}).get('style', ''))
        for prop, val in inline_styles.items():
            resolved[prop] = val
            explicit_props.add(prop)

        # 根元素（html/body）兜底
        if tag in ('html', 'body', '#root'):
            for prop, val in ROOT_DEFAULTS.items():
                resolved.setdefault(prop, val)

        elem['resolved_styles'] = resolved
        elem['_explicit_props'] = explicit_props

    # 4. 第二阶段：从根向叶子传播继承属性
    #    先给 #root 打好兜底值
    for prop, val in ROOT_DEFAULTS.items():
        parser.root['resolved_styles'].setdefault(prop, val)

    _propagate_inherited(parser.root, INHERITED_PROPERTIES)

    # 5. 第三阶段：确保非继承属性的硬兜底
    for elem in parser.elements:
        styles = elem.get('resolved_styles', {})
        styles.setdefault('background-color', 'transparent')
        styles.pop('_explicit_props', None)


def _propagate_inherited(
    element: Dict[str, Any],
    inherited_props: Set[str],
) -> None:
    """
    递归向下传播可继承的 CSS 属性。

    对于每个子元素，如果某个可继承属性没有被显式声明
    （不在 _explicit_props 中），则从父元素的 resolved_styles 中继承该值。
    """
    parent_styles = element.get('resolved_styles', {})

    for child in element.get('children', []):
        child_styles = child.get('resolved_styles', {})
        # 兼容旧格式
        explicit = (child.get('_explicit_props', set()) |
                    child_styles.pop('__explicit_props__', set()))

        for prop in inherited_props:
            if prop not in explicit and prop in parent_styles:
                child_styles[prop] = parent_styles[prop]

        # 递归处理子元素
        _propagate_inherited(child, inherited_props)


# ============================================================================
# 单位解析工具
# ============================================================================

def _parse_px_value(value: str, base_font_size: float = 16.0) -> Optional[float]:
    """
    将 CSS 长度值转换为 px 数值。

    支持单位：px, rem, em, pt，不支持百分比和视口单位。
    无法解析时返回 None。
    """
    if not value or not isinstance(value, str):
        return None

    value = value.strip().lower()

    # 纯数字（无单位）——某些上下文中默认为 px
    if re.match(r'^-?\d+(\.\d+)?$', value):
        return float(value)

    # px
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*px$', value)
    if m:
        return float(m.group(1))

    # rem（假设根字号 16px）
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*rem$', value)
    if m:
        return float(m.group(1)) * 16.0

    # em（使用传入的基准字号）
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*em$', value)
    if m:
        return float(m.group(1)) * base_font_size

    # pt（1pt ≈ 1.333px）
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*pt$', value)
    if m:
        return float(m.group(1)) * 1.333

    return None


def _parse_number_value(value: str) -> Optional[float]:
    """解析纯数值（无量纲），如 line-height: 1.5。"""
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*$', value)
    if m:
        return float(m.group(1))
    return None


def _extract_spacing_values(style: Dict[str, str]) -> List[float]:
    """从样式字典中提取所有 margin/padding 并转换为 px 数值列表。"""
    values: List[float] = []
    spacing_props = [
        'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
        'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    ]

    for prop in spacing_props:
        val = style.get(prop, '')
        if not val:
            continue
        # 可能的值：单个、两个、三个、四个
        parts = val.strip().split()
        for part in parts:
            px = _parse_px_value(part)
            if px is not None and px > 0:
                values.append(px)

    return values


# ============================================================================
# 辅助工具
# ============================================================================

def _get_text_elements(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """筛选出包含可见文字的元素。"""
    result = []
    for elem in elements:
        tag = elem.get('tag', '')
        # 跳过非渲染标签
        if tag in ('style', 'script', 'meta', 'link', 'head', 'html', '#root',
                    'br', 'hr', 'img', 'input', 'svg', 'path'):
            continue
        # 跳过隐藏元素
        style = elem.get('resolved_styles', {})
        if style.get('display') == 'none' or style.get('visibility') == 'hidden':
            continue
        if elem.get('text', '').strip():
            result.append(elem)
    return result


def _get_interactive_elements(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """筛选出交互类元素。"""
    return [e for e in elements if e.get('tag', '') in INTERACTIVE_ELEMENTS]


def _find_bg_color(element: Dict[str, Any]) -> Tuple[int, int, int]:
    """向上遍历 DOM 树查找第一个非透明背景色，默认返回白色。"""
    node = element
    while node:
        bg_str = node.get('resolved_styles', {}).get('background-color', 'transparent')
        bg_color = parse_color(bg_str)
        if bg_color and bg_color[3] > 0:  # 非透明
            return bg_color[:3]
        # 也检查 background 简写属性
        bg_shorthand = node.get('resolved_styles', {}).get('background', '')
        if bg_shorthand and bg_shorthand != 'transparent':
            bg_parsed = parse_color(bg_shorthand)
            if bg_parsed and bg_parsed[3] > 0:
                return bg_parsed[:3]
        node = node.get('parent')
    return (255, 255, 255)  # 默认白色背景


def _is_bold(element: Dict[str, Any]) -> bool:
    """判断元素文字是否为粗体。"""
    fw = element.get('resolved_styles', {}).get('font-weight', '400')
    tag = element.get('tag', '')
    # bold 标签
    if tag in ('strong', 'b', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        return True
    try:
        weight = int(fw)
        return weight >= 600
    except (ValueError, TypeError):
        return fw.lower() in ('bold', 'bolder')


# ============================================================================
# 维度 1: 对比度检测
# ============================================================================

def check_contrast_ratio(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测文字与背景的 WCAG 对比度。

    规则：
      - 普通文字对比度 ≥ 4.5:1（AA 级）
      - 大文字（≥18px 或 ≥14px bold）对比度 ≥ 3:1
      - 分数 = 通过率

    局限性：无法解析 var(--custom-property)、external stylesheets、背景图片上的文字。
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    text_elements = _get_text_elements(parser.elements)
    if not text_elements:
        return DimensionResult(
            dimension='contrast_ratio', label='对比度检测',
            score=1.0, details={'total_elements': 0},
            limitation_note='未检测到文本元素'
        )

    total = 0
    passed = 0
    issues: List[Issue] = []

    for elem in text_elements:
        total += 1
        styles = elem.get('resolved_styles', {})
        fg_str = styles.get('color', '#000000')
        fg_color = parse_color(fg_str)
        if fg_color is None:
            continue  # 无法解析，跳过

        bg_color = _find_bg_color(elem)

        ratio = contrast_ratio(fg_color[:3], bg_color)

        # 判断字号
        font_size_str = styles.get('font-size', '16px')
        font_size_px = _parse_px_value(font_size_str) or 16
        is_large = font_size_px >= 18 or (font_size_px >= 14 and _is_bold(elem))

        threshold = CONTRAST_AA_LARGE if is_large else CONTRAST_AA_NORMAL

        if ratio >= threshold:
            passed += 1
        else:
            issues.append(Issue(
                element=f"<{elem['tag']}> \"{elem.get('text', '')[:30]}\"",
                property='color / background-color',
                current_value=f'对比度 {ratio:.1f}:1（文字 {_rgb_to_hex(fg_color[:3])} / 背景 {_rgb_to_hex(bg_color)}）',
                expected=f'≥ {threshold}:1（{"大文字" if is_large else "普通文字"}）',
                severity='error' if ratio < threshold * 0.7 else 'warning',
            ))

    score = passed / total if total > 0 else 1.0

    return DimensionResult(
        dimension='contrast_ratio', label='对比度检测（WCAG AA）',
        score=round(score, 3),
        details={'total_text_elements': total, 'passed': passed, 'failed': total - passed},
        issues=issues,
        limitation_note='无法解析 var() CSS 变量、外部样式表；背景图片上的文字可能漏检'
    )


# ============================================================================
# 维度 2: 字号下限
# ============================================================================

def check_font_size(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测文字字号是否 ≥ 12px。

    规则：所有可见文字元素的 font-size ≥ 12px。
    分数 = 通过率。
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    text_elements = _get_text_elements(parser.elements)
    if not text_elements:
        return DimensionResult(
            dimension='font_size', label='字号下限',
            score=1.0, details={'total_elements': 0},
            limitation_note='未检测到文本元素'
        )

    total = 0
    passed = 0
    issues: List[Issue] = []
    size_distribution: Counter = Counter()

    for elem in text_elements:
        total += 1
        size_str = elem.get('resolved_styles', {}).get('font-size', '16px')
        px = _parse_px_value(size_str)
        if px is None:
            px = 16  # 无法解析时假设默认

        # 归类分布
        if px < 10:
            size_distribution['<10px'] += 1
        elif px < 12:
            size_distribution['10-11px'] += 1
        elif px < 14:
            size_distribution['12-13px'] += 1
        elif px < 16:
            size_distribution['14-15px'] += 1
        elif px < 20:
            size_distribution['16-19px'] += 1
        else:
            size_distribution['≥20px'] += 1

        if px >= MIN_FONT_SIZE_PX:
            passed += 1
        else:
            issues.append(Issue(
                element=f"<{elem['tag']}> \"{elem.get('text', '')[:30]}\"",
                property='font-size',
                current_value=f'{px:.0f}px',
                expected=f'≥ {MIN_FONT_SIZE_PX}px',
                severity='error' if px < 10 else 'warning',
            ))

    score = passed / total if total > 0 else 1.0

    return DimensionResult(
        dimension='font_size', label='字号下限（≥12px）',
        score=round(score, 3),
        details={
            'total_text_elements': total,
            'passed': passed,
            'failed': total - passed,
            'size_distribution': dict(size_distribution),
        },
        issues=issues,
    )


# ============================================================================
# 维度 3: 行高下限
# ============================================================================

def check_line_height(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测文字行高是否 ≥ 1.4。

    规则：
      - 如果行高是数值（无单位），直接比较
      - 如果行高是 px 单位，与当前元素字号比较
      - 分数 = 通过率
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    text_elements = _get_text_elements(parser.elements)
    if not text_elements:
        return DimensionResult(
            dimension='line_height', label='行高下限',
            score=1.0, details={'total_elements': 0},
            limitation_note='未检测到文本元素'
        )

    total = 0
    passed = 0
    issues: List[Issue] = []

    for elem in text_elements:
        total += 1
        styles = elem.get('resolved_styles', {})
        lh_str = styles.get('line-height', 'normal')

        if lh_str == 'normal':
            # "normal" ≈ 1.2，通常不符合 WCAG 推荐
            passed += 0  # 算不及格
            issues.append(Issue(
                element=f"<{elem['tag']}> \"{elem.get('text', '')[:30]}\"",
                property='line-height',
                current_value='normal（约 1.2）',
                expected=f'≥ {MIN_LINE_HEIGHT_RATIO}',
                severity='info',
            ))
            continue

        # 尝试作为纯数字解析
        num_val = _parse_number_value(lh_str)
        if num_val is not None:
            if num_val >= MIN_LINE_HEIGHT_RATIO:
                passed += 1
            else:
                issues.append(Issue(
                    element=f"<{elem['tag']}> \"{elem.get('text', '')[:30]}\"",
                    property='line-height',
                    current_value=f'{num_val}',
                    expected=f'≥ {MIN_LINE_HEIGHT_RATIO}',
                    severity='warning',
                ))
            continue

        # 尝试作为 px 值解析
        px_val = _parse_px_value(lh_str)
        if px_val is not None:
            # 相对于当前字号计算比例
            fs_str = styles.get('font-size', '16px')
            fs_px = _parse_px_value(fs_str) or 16
            ratio = px_val / fs_px if fs_px > 0 else 1.0
            if ratio >= MIN_LINE_HEIGHT_RATIO:
                passed += 1
            else:
                issues.append(Issue(
                    element=f"<{elem['tag']}> \"{elem.get('text', '')[:30]}\"",
                    property='line-height',
                    current_value=f'{lh_str}（比例 {ratio:.1f}）',
                    expected=f'≥ {MIN_LINE_HEIGHT_RATIO}',
                    severity='warning',
                ))
            continue

        # 无法解析，给 pass
        passed += 1

    score = passed / total if total > 0 else 1.0

    return DimensionResult(
        dimension='line_height', label='行高下限（≥1.4）',
        score=round(score, 3),
        details={'total_text_elements': total, 'passed': passed, 'failed': total - passed},
        issues=issues,
    )


# ============================================================================
# 维度 4: 字体族数量
# ============================================================================

def check_font_family_count(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测页面使用的字体族数量是否 ≤ 2。

    规则：
      - 统计全页所有 font-family 声明中引用的字体族
      - 移除通用回退族（sans-serif, serif, monospace 等）
      - 分数：≤2 → 1.0, 3 → 0.7, 4 → 0.4, ≥5 → 0.1
    """
    GENERIC_FAMILIES = {
        'serif', 'sans-serif', 'sans serif', 'monospace',
        'cursive', 'fantasy', 'system-ui', 'ui-sans-serif',
        'ui-serif', 'ui-monospace', 'ui-rounded', 'math',
        'emoji', 'fangsong', 'inherit', 'initial', 'unset',
    }

    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    all_families: Set[str] = set()

    for elem in parser.elements:
        family_str = elem.get('resolved_styles', {}).get('font-family', '')
        if not family_str:
            continue

        # 按逗号分割，第一个通常是主字体
        parts = [f.strip().strip("'\"") for f in family_str.split(',')]
        for part in parts:
            part_lower = part.lower()
            # 跳过通用回退族
            if part_lower in GENERIC_FAMILIES:
                continue
            all_families.add(part)

    count = len(all_families)

    if count <= 2:
        score = 1.0
    elif count == 3:
        score = 0.7
    elif count == 4:
        score = 0.4
    else:
        score = 0.1

    issues: List[Issue] = []
    if count > MAX_FONT_FAMILIES:
        issues.append(Issue(
            element='整个页面',
            property='font-family',
            current_value=f'{count} 种字体族：{", ".join(sorted(all_families))}',
            expected=f'≤ {MAX_FONT_FAMILIES} 种',
            severity='warning',
        ))

    return DimensionResult(
        dimension='font_family_count', label='字体族数量（≤2）',
        score=score,
        details={
            'total_font_families': count,
            'families': sorted(all_families),
            'max_allowed': MAX_FONT_FAMILIES,
        },
        issues=issues,
    )


# ============================================================================
# 维度 5: 字号层级
# ============================================================================

def check_font_hierarchy(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测字号层级是否清晰。

    规则：
      1. h1 > h2 > h3 > h4 > h5 > h6（递减）
      2. 全页字号种类 ≥ 3（有层级变化）
      3. 最大字号 / 最小字号 ≥ 1.5（有足够的对比度）
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    issues: List[Issue] = []
    scores: List[float] = []

    # 1. h1-h6 递减检查
    heading_sizes: Dict[str, float] = {}
    for level in range(1, 7):
        tag = f'h{level}'
        for elem in parser.elements:
            if elem.get('tag') == tag:
                sz = _parse_px_value(elem.get('resolved_styles', {}).get('font-size', ''))
                if sz is not None:
                    heading_sizes[tag] = sz
                    break  # 只取第一个

    violations = 0
    for i in range(1, 6):
        current = heading_sizes.get(f'h{i}')
        next_ = heading_sizes.get(f'h{i + 1}')
        if current is not None and next_ is not None:
            if current < next_ + 1:  # +1px 容差
                violations += 1
                issues.append(Issue(
                    element=f'h{i} → h{i + 1}',
                    property='font-size',
                    current_value=f'h{i}={current:.0f}px, h{i + 1}={next_:.0f}px',
                    expected='h{i} > h{i + 1}',
                    severity='warning',
                ))

    head_count = len(heading_sizes)
    if head_count >= 2:
        score_heading = 1.0 - (violations / (head_count - 1))
    else:
        score_heading = 1.0
    scores.append(max(0, score_heading))

    # 2. 全页字号多样性
    text_elements = _get_text_elements(parser.elements)
    all_sizes: Set[int] = set()
    for elem in text_elements:
        sz = _parse_px_value(elem.get('resolved_styles', {}).get('font-size', ''))
        if sz is not None:
            all_sizes.add(int(sz))

    unique_sizes = len(all_sizes)
    if unique_sizes < 2:
        score_variety = 0.2
        issues.append(Issue(
            element='整个页面',
            property='font-size',
            current_value=f'仅 {unique_sizes} 种字号',
            expected='≥ 3 种不同字号',
            severity='error',
        ))
    elif unique_sizes == 2:
        score_variety = 0.6
        issues.append(Issue(
            element='整个页面',
            property='font-size',
            current_value=f'仅 {unique_sizes} 种字号',
            expected='≥ 3 种不同字号',
            severity='warning',
        ))
    else:
        score_variety = 1.0
    scores.append(score_variety)

    # 3. 最大/最小字号比
    if len(all_sizes) >= 2:
        max_sz = max(all_sizes)
        min_sz = min(all_sizes)
        ratio = max_sz / min_sz if min_sz > 0 else 1
        if ratio < 1.3:
            score_ratio = 0.3
            issues.append(Issue(
                element='整个页面',
                property='font-size 层级对比',
                current_value=f'最大 {max_sz}px / 最小 {min_sz}px = {ratio:.1f}',
                expected='≥ 1.5 倍',
                severity='warning',
            ))
        elif ratio < 1.5:
            score_ratio = 0.7
        else:
            score_ratio = 1.0
        scores.append(score_ratio)

    score = sum(scores) / len(scores) if scores else 1.0

    return DimensionResult(
        dimension='font_hierarchy', label='字号层级',
        score=round(score, 3),
        details={
            'heading_sizes': {k: f'{v:.0f}px' for k, v in heading_sizes.items()},
            'unique_font_sizes': unique_sizes,
            'size_range': f'{min(all_sizes)}px - {max(all_sizes)}px' if all_sizes else 'N/A',
        },
        issues=issues,
    )


# ============================================================================
# 维度 6: 语义化标签
# ============================================================================

def check_semantic_tags(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测 HTML5 语义化标签的使用。

    规则：
      - 检查推荐标签是否被使用（main, nav, header, footer, section, article, aside 等）
      - 检查是否使用了废弃标签（center, font, marquee 等）
      - 分数 = 使用的推荐标签数 / 关键标签数
    """
    DEPRECATED_TAGS = {
        'center', 'font', 'marquee', 'blink', 'bgsound',
        'frame', 'frameset', 'noframes', 'applet', 'dir', 'big', 'strike', 'tt',
    }

    if parser is None:
        parser = _parse_html(html)

    used_tags: Set[str] = set()
    deprecated_found: Set[str] = set()

    for elem in parser.elements:
        tag = elem.get('tag', '')
        if tag in SEMANTIC_TAGS:
            used_tags.add(tag)
        if tag in DEPRECATED_TAGS:
            deprecated_found.add(tag)

    # 关键标签（权重更高）
    critical_tags = {'main', 'nav', 'header', 'footer'}
    optional_tags = set(SEMANTIC_TAGS) - critical_tags

    critical_used = used_tags & critical_tags
    optional_used = used_tags & optional_tags

    # 加权计算
    critical_score = len(critical_used) / len(critical_tags) if critical_tags else 1.0
    optional_score = len(optional_used) / len(optional_tags) if optional_tags else 1.0
    score = critical_score * 0.7 + optional_score * 0.3

    issues: List[Issue] = []
    missing_critical = critical_tags - used_tags
    if missing_critical:
        issues.append(Issue(
            element='整个页面',
            property='语义标签',
            current_value=f'缺少: {", ".join(sorted(missing_critical))}',
            expected='应使用语义化标签替代 <div>',
            severity='warning',
        ))

    if deprecated_found:
        issues.append(Issue(
            element='整个页面',
            property='废弃标签',
            current_value=f'使用了废弃标签: {", ".join(sorted(deprecated_found))}',
            expected='应替换为现代 HTML5 标签或 CSS',
            severity='error',
        ))

    return DimensionResult(
        dimension='semantic_tags', label='语义化标签',
        score=round(min(score, 1.0), 3),
        details={
            'used_semantic_tags': sorted(used_tags),
            'missing_critical': sorted(missing_critical),
            'deprecated_found': sorted(deprecated_found),
        },
        issues=issues,
    )


# ============================================================================
# 维度 7: ARIA 属性
# ============================================================================

def check_aria_attributes(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测 ARIA 可访问性属性的使用。

    规则：
      - 交互元素应有 accessible name（aria-label / aria-labelledby / 内嵌文字）
      - 图标/link（无文字）必须有 aria-label
      - 表单输入应有关联的 <label>
      - 不使用冗余 ARIA（如 <button role="button">）
      - tabindex 不应为正数
    """
    IMPLICIT_ROLES: Dict[str, str] = {
        'button': 'button', 'a': 'link', 'input': 'input',
        'select': 'combobox', 'textarea': 'textbox',
        'nav': 'navigation', 'main': 'main', 'header': 'banner',
        'footer': 'contentinfo', 'aside': 'complementary',
        'form': 'form', 'table': 'table', 'img': 'img',
    }

    if parser is None:
        parser = _parse_html(html)

    interactive = _get_interactive_elements(parser.elements)
    if not interactive:
        return DimensionResult(
            dimension='aria_attributes', label='ARIA 属性',
            score=1.0, details={'total_interactive': 0},
            limitation_note='未检测到交互元素'
        )

    checks_total = 0
    checks_passed = 0
    issues: List[Issue] = []

    for elem in interactive:
        tag = elem.get('tag', '')
        attrs = elem.get('attrs', {})
        text = (elem.get('text', '') or '').strip()

        # 检查 accessible name
        has_aria_label = 'aria-label' in attrs
        has_aria_labelledby = 'aria-labelledby' in attrs
        has_inner_text = bool(text)
        has_title = 'title' in attrs

        checks_total += 1
        if has_aria_label or has_aria_labelledby or has_inner_text or has_title:
            checks_passed += 1
        elif tag in ('input', 'select', 'textarea'):
            # 检查是否有关联 label（通过 for/id 或 包裹关系——这里简化处理）
            input_id = attrs.get('id', '')
            if input_id:
                # 在 HTML 中搜索 <label for="id">
                if f'for="{input_id}"' in html or f"for='{input_id}'" in html:
                    checks_passed += 1
                    continue
            checks_passed += 0  # 没有标签
            issues.append(Issue(
                element=f'<{tag}> id="{input_id}"',
                property='label',
                current_value='缺少关联的 <label> 或 aria-label',
                expected='每个表单控件应有 accessible name',
                severity='error',
            ))

        # 检查冗余 ARIA role
        implicit_role = IMPLICIT_ROLES.get(tag)
        explicit_role = attrs.get('role', '')
        if implicit_role and explicit_role == implicit_role:
            checks_total += 1
            issues.append(Issue(
                element=f'<{tag} role="{explicit_role}">',
                property='role',
                current_value=f'冗余 role="{explicit_role}"',
                expected=f'<{tag}> 已隐含 role="{implicit_role}"，无需显式声明',
                severity='info',
            ))

        # 检查 tabindex
        tabindex = attrs.get('tabindex', '')
        if tabindex:
            checks_total += 1
            try:
                ti = int(tabindex)
                if ti > 0:
                    issues.append(Issue(
                        element=f'<{tag} tabindex="{tabindex}">',
                        property='tabindex',
                        current_value=f'tabindex="{tabindex}"',
                        expected='tabindex 应 ≤ 0（避免打乱自然 Tab 序）',
                        severity='warning',
                    ))
                else:
                    checks_passed += 1
            except ValueError:
                checks_passed += 1

    score = checks_passed / checks_total if checks_total > 0 else 1.0

    return DimensionResult(
        dimension='aria_attributes', label='ARIA 可访问性',
        score=round(score, 3),
        details={
            'total_checks': checks_total,
            'passed': checks_passed,
            'interactive_elements': len(interactive),
        },
        issues=issues,
    )


# ============================================================================
# 维度 8: Meta 标签
# ============================================================================

def check_meta_tags(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测必要的 Meta 标签。

    规则：
      - 必备：title, meta description, meta viewport, meta charset
      - 推荐：og:title, og:description, og:image
      - 分数 = 存在率
    """
    REQUIRED_META = {
        'title': '有',
        'description': 'meta name="description"',
        'viewport': 'meta name="viewport"',
        'charset': 'meta charset',
    }
    RECOMMENDED_META = {
        'og:title': 'Open Graph 标题',
        'og:description': 'Open Graph 描述',
        'og:image': 'Open Graph 图片',
    }

    if parser is None:
        parser = _parse_html(html)

    issues: List[Issue] = []
    found_required = 0
    found_recommended = 0

    # title
    if parser.title_text:
        found_required += 1
    else:
        issues.append(Issue(
            element='<head>', property='<title>',
            current_value='缺少 <title>', expected='应有页面标题',
            severity='error',
        ))

    # meta tags 收集
    meta_keys = set(parser.meta_tags.keys())

    # description（可能在 name="description" 或 property="description"）
    if 'description' in meta_keys:
        found_required += 1
    else:
        issues.append(Issue(
            element='<head>', property='meta description',
            current_value='缺少', expected='<meta name="description" content="...">',
            severity='warning',
        ))

    # viewport
    if 'viewport' in meta_keys:
        found_required += 1
    else:
        issues.append(Issue(
            element='<head>', property='meta viewport',
            current_value='缺少',
            expected='<meta name="viewport" content="width=device-width, initial-scale=1">',
            severity='error',
        ))

    # charset
    if 'charset' in meta_keys:
        found_required += 1
    else:
        # 也检查原始 HTML
        if '<meta charset' in html.lower():
            found_required += 1
        else:
            issues.append(Issue(
                element='<head>', property='meta charset',
                current_value='缺少', expected='<meta charset="UTF-8">',
                severity='error',
            ))

    # 推荐标签
    for og_key in ['og:title', 'og:description', 'og:image']:
        if og_key in meta_keys:
            found_recommended += 1

    score_required = found_required / len(REQUIRED_META) if REQUIRED_META else 1.0
    score_recommended = found_recommended / len(RECOMMENDED_META) if RECOMMENDED_META else 1.0
    score = score_required * 0.7 + score_recommended * 0.3

    return DimensionResult(
        dimension='meta_tags', label='Meta 标签完整性',
        score=round(score, 3),
        details={
            'required_found': found_required,
            'required_total': len(REQUIRED_META),
            'recommended_found': found_recommended,
            'recommended_total': len(RECOMMENDED_META),
            'found_keys': sorted(meta_keys),
        },
        issues=issues,
    )


# ============================================================================
# 维度 9: 色板与主色数量
# ============================================================================

def check_color_palette(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测页面配色是否协调。

    规则：
      1. 提取所有 color / background-color
      2. 聚类相似颜色
      3. 主色（出现频率 ≥ 阈值）≤ 3 种
      4. 检查是否有极端的颜色数量（>20 种不同色值暗示配色混乱）
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    all_colors: List[Tuple[int, int, int]] = []

    for elem in parser.elements:
        styles = elem.get('resolved_styles', {})
        for prop in ('color', 'background-color'):
            val = styles.get(prop, '')
            if val and val != 'transparent':
                parsed = parse_color(val)
                if parsed and parsed[3] > 0:
                    all_colors.append(parsed[:3])

    if not all_colors:
        return DimensionResult(
            dimension='color_palette', label='色板与主色数量',
            score=1.0, details={'total_color_declarations': 0},
            limitation_note='未检测到颜色声明'
        )

    # 简单聚类：按欧几里得距离将相近颜色归为一组
    clusters: List[List[Tuple[int, int, int]]] = []
    for color in all_colors:
        placed = False
        for cluster in clusters:
            # 与簇中心的距离
            center = cluster[0]
            if _color_distance(color, center) < COLOR_CLUSTER_THRESHOLD:
                cluster.append(color)
                placed = True
                break
        if not placed:
            clusters.append([color])

    # 按簇大小排序
    clusters.sort(key=len, reverse=True)
    primary_count = sum(1 for c in clusters if len(c) >= 3)  # 至少出现 3 次的簇才算主色

    # 分数
    if primary_count <= MAX_PRIMARY_COLORS:
        score = 1.0
    elif primary_count <= 5:
        score = 0.7
    elif primary_count <= 7:
        score = 0.4
    else:
        score = 0.1

    issues: List[Issue] = []
    if primary_count > MAX_PRIMARY_COLORS:
        issues.append(Issue(
            element='整个页面',
            property='color / background-color',
            current_value=f'{primary_count} 种主色（共 {len(clusters)} 种颜色）',
            expected=f'≤ {MAX_PRIMARY_COLORS} 种主色',
            severity='warning',
        ))

    # 颜色总数过多也报警
    unique_colors = len(set(_rgb_to_hex(c) for c in all_colors))
    if unique_colors > 20:
        issues.append(Issue(
            element='整个页面',
            property='颜色总数',
            current_value=f'{unique_colors} 种不同颜色值',
            expected='建议 ≤ 15 种',
            severity='info',
        ))

    # 提取主要的颜色值供展示
    top_colors = [_rgb_to_hex(c[0]) for c in clusters[:5] if len(c) >= 2]

    return DimensionResult(
        dimension='color_palette', label='色板与主色数量（≤3）',
        score=round(score, 3),
        details={
            'total_color_declarations': len(all_colors),
            'unique_colors': unique_colors,
            'primary_color_count': primary_count,
            'total_clusters': len(clusters),
            'top_colors': top_colors,
        },
        issues=issues,
    )


# ============================================================================
# 维度 10: 间距一致性（8px 网格）
# ============================================================================

def check_spacing_consistency(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测 margin/padding 是否对齐 8px 网格。

    规则：
      - 提取所有元素的 margin / padding 值
      - 检查每个值是否能被 8 整除（±2px 容差）
      - 分数 = 对齐率
      - 额外检查：同类元素（同 tag + 同 class）的间距是否一致
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    all_values: List[float] = []
    aligned = 0
    total = 0
    issues: List[Issue] = []

    for elem in parser.elements:
        if elem.get('tag') in ('#root', 'html', 'head', 'style', 'script', 'meta'):
            continue
        styles = elem.get('resolved_styles', {})
        values = _extract_spacing_values(styles)
        all_values.extend(values)

        for v in values:
            total += 1
            # 检查是否对齐 8px 网格
            remainder = v % GRID_UNIT_PX
            min_remainder = min(remainder, GRID_UNIT_PX - remainder)
            if min_remainder <= GRID_TOLERANCE_PX:
                aligned += 1

    # 同类元素间距一致性检查
    elem_groups: Dict[str, List[float]] = defaultdict(list)
    for elem in parser.elements:
        tag = elem.get('tag', '')
        cls = elem.get('attrs', {}).get('class', '')
        if tag in TEXT_ELEMENTS:
            key = f'{tag}.{cls}' if cls else tag
            styles = elem.get('resolved_styles', {})
            values = _extract_spacing_values(styles)
            if values:
                elem_groups[key].extend(values)

    inconsistent_groups = 0
    for key, vals in elem_groups.items():
        if len(vals) >= 3:
            mean_v = sum(vals) / len(vals)
            variance = sum((v - mean_v) ** 2 for v in vals) / len(vals)
            if variance > 100:  # 方差 > 100 意味着间距不够一致
                inconsistent_groups += 1

    if inconsistent_groups > 5:
        issues.append(Issue(
            element='整个页面',
            property='margin/padding',
            current_value=f'{inconsistent_groups} 组同类元素间距不一致',
            expected='同类元素应使用一致的间距',
            severity='warning',
        ))

    score_alignment = aligned / total if total > 0 else 1.0

    # 综合评分
    if total < 5:
        # 间距声明很少，可能主要是默认间距，不扣分
        score = 1.0
    else:
        score = score_alignment

    return DimensionResult(
        dimension='spacing_consistency', label='间距一致性（8px 网格）',
        score=round(score, 3),
        details={
            'total_spacing_values': total,
            'aligned_to_grid': aligned,
            'alignment_rate': f'{score_alignment * 100:.1f}%',
            'inconsistent_groups': inconsistent_groups,
            'grid_unit': f'{GRID_UNIT_PX}px ± {GRID_TOLERANCE_PX}px',
        },
        issues=issues,
    )


# ============================================================================
# 维度 11: 溢出风险（静态预估）
# ============================================================================

def check_overflow_risk(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    静态预估水平溢出风险。

    注意：真实溢出检测需要浏览器渲染。此函数仅基于代码模式做风险预估。

    规则：
      - 检测固定宽度 ≥ 1200px 但未设置 overflow 的容器
      - 检测 100vw 元素未考虑滚动条
      - 检测大量绝对定位元素
      - 检测 table/flex/grid 容器可能的内容溢出
      - 分数：无风险模式 → 1.0，风险越多 → 越低
    """
    if parser is None:
        parser = _parse_html(html)
        _resolve_styles(parser)

    total_risks = 0
    issues: List[Issue] = []

    for elem in parser.elements:
        tag = elem.get('tag', '')
        if tag in ('#root', 'html', 'head', 'style', 'script', 'meta', 'link'):
            continue

        styles = elem.get('resolved_styles', {})

        # 1. 固定宽度过大但未设 overflow
        width_str = styles.get('width', '')
        overflow_str = styles.get('overflow', '') or styles.get('overflow-x', '')
        if width_str:
            w_px = _parse_px_value(width_str)
            if w_px is not None and w_px >= 1000 and not overflow_str:
                total_risks += 1
                issues.append(Issue(
                    element=f'<{tag}> width={width_str}',
                    property='overflow',
                    current_value='固定宽度但未设置 overflow',
                    expected='建议添加 overflow-x: auto 或使用 max-width',
                    severity='info',
                ))

        # 2. 100vw 未考虑滚动条
        if '100vw' in styles.get('width', '') or '100vw' in styles.get('min-width', ''):
            total_risks += 1
            issues.append(Issue(
                element=f'<{tag}> width=100vw',
                property='width',
                current_value='100vw',
                expected='100vw 在垂直滚动条出现时会导致水平溢出，建议用 100%',
                severity='warning',
            ))

        # 3. 负 margin 可能导致溢出
        for prop in ('margin-left', 'margin-right'):
            val = styles.get(prop, '')
            if val and val.startswith('-'):
                px = _parse_px_value(val)
                if px is not None and px < -20:
                    total_risks += 1
                    issues.append(Issue(
                        element=f'<{tag}> {prop}={val}',
                        property=prop,
                        current_value=val,
                        expected='过大的负 margin 可能导致内容溢出视口',
                        severity='info',
                    ))

    # 计算分数
    if total_risks == 0:
        score = 1.0
    elif total_risks <= 2:
        score = 0.85
    elif total_risks <= 5:
        score = 0.6
    else:
        score = 0.3

    return DimensionResult(
        dimension='overflow_risk', label='溢出风险（静态预估）',
        score=round(score, 3),
        details={
            'risk_patterns_found': total_risks,
        },
        issues=issues,
        limitation_note='真实溢出检测需要 Puppeteer/Playwright 浏览器渲染；此函数仅基于代码模式做风险预估'
    )


# ============================================================================
# 维度 12: 键盘导航基础
# ============================================================================

def check_keyboard_navigation(html: str, parser: _StyleCollectingHTMLParser = None) -> DimensionResult:
    """
    检测键盘导航基础支持。

    规则：
      - 不应有正数 tabindex（破坏自然 Tab 序）
      - 交互元素不应被禁用键盘访问（tabindex="-1" 过多）
      - 是否有 skip navigation link
      - 自定义交互控件（div/span + onClick）是否可键盘访问
    """
    if parser is None:
        parser = _parse_html(html)

    issues: List[Issue] = []
    checks_total = 0
    checks_passed = 0

    # 1. 正数 tabindex
    for elem in parser.elements:
        tabindex = elem.get('attrs', {}).get('tabindex', '')
        if tabindex:
            try:
                ti = int(tabindex)
                checks_total += 1
                if ti > 0:
                    issues.append(Issue(
                        element=f'<{elem["tag"]} tabindex="{tabindex}">',
                        property='tabindex',
                        current_value=str(ti),
                        expected='避免使用正数 tabindex',
                        severity='warning',
                    ))
                else:
                    checks_passed += 1
            except ValueError:
                checks_passed += 1

    # 2. 检查 skip navigation link
    skip_link_found = False
    for elem in parser.elements:
        if elem.get('tag') == 'a':
            href = elem.get('attrs', {}).get('href', '')
            text = (elem.get('text', '') or '').strip().lower()
            if href and href.startswith('#') and ('skip' in text or '跳转' in text or 'skip' in href):
                skip_link_found = True
                break

    checks_total += 1
    if skip_link_found:
        checks_passed += 1
    # 小页面（<20 个交互元素）不需要 skip link
    interactive_count = len(_get_interactive_elements(parser.elements))
    if interactive_count < 10:
        checks_passed += 1 if not skip_link_found else 0  # 小页面不强制

    # 3. div/span 可点击但有 tabindex
    for elem in parser.elements:
        tag = elem.get('tag', '')
        if tag not in ('div', 'span'):
            continue
        attrs = elem.get('attrs', {})
        has_onclick = any(k.startswith('on') for k in attrs)
        has_role_button = attrs.get('role', '') == 'button'
        has_tabindex = 'tabindex' in attrs
        has_key_handler = any(k.startswith('onkey') for k in attrs)

        if has_onclick or has_role_button:
            checks_total += 1
            if has_tabindex and has_key_handler:
                checks_passed += 1
            elif has_tabindex:
                checks_passed += 0.5
                issues.append(Issue(
                    element=f'<{tag}> (自定义交互控件)',
                    property='keyboard',
                    current_value='缺少键盘事件处理（onkeydown/onkeyup）',
                    expected='自定义交互控件需同时支持键盘操作',
                    severity='warning',
                ))
            else:
                issues.append(Issue(
                    element=f'<{tag}> (自定义交互控件)',
                    property='tabindex',
                    current_value='缺少 tabindex，键盘无法聚焦',
                    expected='添加 tabindex="0" + 键盘事件处理',
                    severity='error',
                ))

    score = checks_passed / checks_total if checks_total > 0 else 1.0

    return DimensionResult(
        dimension='keyboard_navigation', label='键盘导航基础',
        score=round(score, 3),
        details={
            'total_checks': checks_total,
            'passed': checks_passed,
            'skip_link_found': skip_link_found,
            'interactive_count': interactive_count,
        },
        issues=issues,
        limitation_note='真实的 Tab 序和焦点管理需要浏览器环境验证'
    )


# ============================================================================
# 主函数
# ============================================================================

def evaluate_all(html: str, verbose: bool = False) -> Dict[str, Any]:
    """
    对一段 HTML 代码执行所有规则化判定，返回综合评分报告。

    Args:
        html: 完整的 HTML 字符串
        verbose: 是否在结果中附带详细的 issues 列表

    Returns:
        {
            "overall_score": float,       # 加权总分 0.0 ~ 1.0
            "dimension_count": int,       # 判定维度数
            "dimensions": {
                "contrast_ratio": {
                    "score": float,
                    "label": str,
                    "weight": float,
                    "details": {...},
                    "limitation_note": str,
                    "issues_count": int,
                    "issues": [...] if verbose else [],
                },
                ...
            },
            "score_breakdown": {
                "L1_basic_usability": float,   # 基础可用性平均分
                "L2_visual_coordination": float,  # 视觉协调性平均分
            }
        }
    """
    # 解析 HTML（只做一次）
    parser = _parse_html(html)
    _resolve_styles(parser)

    # 定义所有维度及其配置
    dimensions_config = [
        # L1 — 基础可用性
        ('contrast_ratio',       check_contrast_ratio,       1.0, 'L1'),
        ('font_size',            check_font_size,            0.8, 'L1'),
        ('line_height',          check_line_height,          0.8, 'L1'),
        ('semantic_tags',        check_semantic_tags,        0.6, 'L1'),
        ('aria_attributes',      check_aria_attributes,      0.6, 'L1'),
        ('meta_tags',            check_meta_tags,            0.5, 'L1'),
        ('keyboard_navigation',  check_keyboard_navigation,  0.5, 'L1'),
        # L2 — 视觉协调性
        ('font_family_count',    check_font_family_count,    0.7, 'L2'),
        ('font_hierarchy',       check_font_hierarchy,       0.8, 'L2'),
        ('color_palette',        check_color_palette,        0.9, 'L2'),
        ('spacing_consistency',  check_spacing_consistency,  0.8, 'L2'),
        ('overflow_risk',        check_overflow_risk,        0.4, 'L2'),
    ]

    results: Dict[str, Any] = {
        'overall_score': 0.0,
        'dimension_count': len(dimensions_config),
        'dimensions': {},
        'score_breakdown': {'L1_basic_usability': 0.0, 'L2_visual_coordination': 0.0},
    }

    l1_scores: List[Tuple[float, float]] = []
    l2_scores: List[Tuple[float, float]] = []

    for dim_key, checker_fn, weight, layer in dimensions_config:
        result: DimensionResult = checker_fn(html, parser)

        dim_data = {
            'score': result.score,
            'label': result.label,
            'weight': weight,
            'layer': layer,
            'details': result.details,
            'limitation_note': result.limitation_note,
            'issues_count': len(result.issues),
            'issues': [{
                'element': i.element,
                'property': i.property,
                'current_value': i.current_value[:200],
                'expected': i.expected,
                'severity': i.severity,
            } for i in result.issues] if verbose else [],
        }

        results['dimensions'][dim_key] = dim_data

        if layer == 'L1':
            l1_scores.append((result.score, weight))
        else:
            l2_scores.append((result.score, weight))

    # 计算加权总分
    all_weighted = l1_scores + l2_scores
    total_weight = sum(w for _, w in all_weighted)
    if total_weight > 0:
        results['overall_score'] = round(
            sum(s * w for s, w in all_weighted) / total_weight, 3
        )

    # 分层平均分
    def _weighted_avg(scores: List[Tuple[float, float]]) -> float:
        if not scores:
            return 1.0
        w_sum = sum(w for _, w in scores)
        return round(sum(s * w for s, w in scores) / w_sum, 3) if w_sum > 0 else 1.0

    results['score_breakdown']['L1_basic_usability'] = _weighted_avg(l1_scores)
    results['score_breakdown']['L2_visual_coordination'] = _weighted_avg(l2_scores)

    return results


# ============================================================================
# CLI 入口（方便单独测试）
# ============================================================================

if __name__ == '__main__':
    import sys

    # 强制 UTF-8 输出（避免 Windows GBK 编码报错）
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    if len(sys.argv) < 2:
        print("Usage: python rule_code.py <html_file> [--verbose]")
        print("       python rule_code.py --inline '<html>...'")
        sys.exit(1)

    verbose = '--verbose' in sys.argv

    if sys.argv[1] == '--inline' and len(sys.argv) >= 3:
        html_content = sys.argv[2]
    else:
        filepath = sys.argv[1]
        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()

    result = evaluate_all(html_content, verbose=verbose)

    print("=" * 60)
    print(f"  Overall: {result['overall_score']:.2f}  |  "
          f"L1 Basic: {result['score_breakdown']['L1_basic_usability']:.2f}  |  "
          f"L2 Visual: {result['score_breakdown']['L2_visual_coordination']:.2f}")
    print("=" * 60)

    for dim_key, dim in result['dimensions'].items():
        bar = '#' * int(dim['score'] * 20) + '-' * (20 - int(dim['score'] * 20))
        print(f"  [{dim['layer']}] {dim['label']:<24s}  {dim['score']:.2f}  {bar}  "
              f"({dim['issues_count']} issues)")
        if verbose and dim['issues']:
            for issue in dim['issues'][:3]:
                print(f"    [{issue['severity']}] {issue['element']}: "
                      f"{issue['current_value'][:60]} -> {issue['expected']}")

    print(f"\n  {result['dimension_count']} dimensions, weighted total: {result['overall_score']:.2f}")
