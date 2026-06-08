"""公式检测启发式 — Unicode 数学符号 + LaTeX 命令识别。

从 pdf.py 提取为独立模块，无需依赖 PDFMixin。
"""

from __future__ import annotations

import re

# ── 正则常量 ──

# Unicode 数学符号区域
_MATH_UNICODE = re.compile(
    r"[∀-⋿←-⇿⟀-⟯⦀-⧿⨀-⫿"
    r"Α-ωϑϕϖϰϱϴϵ϶"
    r"℀-⅏⌀-⏿■-◿☀-⛿]"
)

# LaTeX 命令
_LATEX_CMDS = re.compile(
    r"\\(?:frac|sum|int|prod|sqrt|lim|partial|nabla|infty|times|div|pm|mp"
    r"|alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu"
    r"|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega"
    r"|Alpha|Beta|Gamma|Delta|Epsilon|Zeta|Eta|Theta|Iota|Kappa|Lambda|Mu|Nu"
    r"|Xi|Pi|Rho|Sigma|Tau|Upsilon|Phi|Chi|Psi|Omega"
    r"|leq|geq|neq|approx|equiv|sim|propto|in|ni|subset|supset|subseteq"
    r"|cup|cap|setminus|oplus|otimes|cdot|circ|bullet"
    r"|rightarrow|leftarrow|Rightarrow|Leftarrow|leftrightarrow|mapsto"
    r"|forall|exists|neg|wedge|vee|implies|iff"
    r"|mathbb|mathcal|mathbf|mathit|mathrm|textrm|text|hat|bar|tilde|vec|dot|ddot"
    r"|begin|end|left|right|middle|big|Big|bigg|Bigg"
    r"|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan"
    r"|log|ln|exp|det|dim|ker|deg|gcd|hom|min|max|sup|inf|Pr)"
)

# 行间公式定界符
_DISPLAY_MATH = re.compile(r"\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]")
_INLINE_MATH = re.compile(r"\$[^$]+?\$")


def is_formula_block(text: str) -> bool:
    r"""启发式判断文本块是否包含数学公式。

    检测条件（满足任一即判定为公式）：
    1. 包含行间公式定界符 $$...$$ 或 \[...\]
    2. LaTeX 命令密度 > 阈值
    3. Unicode 数学符号密度 > 阈值
    """
    if not text or len(text) < 3:
        return False

    # 条件1: 行间公式定界符
    if _DISPLAY_MATH.search(text):
        return True

    # 条件2+3: 符号密度
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        if len(line) < 8:
            continue

        # LaTeX 命令计数
        latex_matches = len(_LATEX_CMDS.findall(line))
        # Unicode 数学符号计数
        math_chars = len(_MATH_UNICODE.findall(line))
        # 内联数学 $$
        inline_math = len(_INLINE_MATH.findall(line))

        total_chars = len(line)

        # 高密度 LaTeX（每 20 字符有 1 个命令 + 符号）
        formula_score = latex_matches * 3 + math_chars * 2 + inline_math * 5
        if formula_score > 0 and total_chars / max(formula_score, 1) < 15:
            return True

        # 行完全由数学符号组成（至少 30%）
        if math_chars > 0 and math_chars / max(total_chars, 1) > 0.3:
            return True

    return False
