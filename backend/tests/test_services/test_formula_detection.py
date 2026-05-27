"""公式检测启发式 _is_formula_block 单元测试。"""

import pytest

from src.services.document_processors.pdf import _is_formula_block


@pytest.mark.unit
def test_empty_or_short_text() -> None:
    assert _is_formula_block("") is False
    assert _is_formula_block("ab") is False


@pytest.mark.unit
def test_display_math_dollar() -> None:
    assert _is_formula_block("$$E = mc^2$$") is True


@pytest.mark.unit
def test_display_math_bracket() -> None:
    assert _is_formula_block(r"\[E = mc^2\]") is True


@pytest.mark.unit
def test_latex_command_density() -> None:
    text = (
        r"\frac{\partial u}{\partial t} = "
        r"\nabla \cdot (D \nabla u) + f(u)"
    )
    assert _is_formula_block(text) is True


@pytest.mark.unit
def test_unicode_math_density() -> None:
    text = "∀ε > 0, ∃δ > 0: |x - a| < δ ⇒ |f(x) - L| < ε"
    assert _is_formula_block(text) is True


@pytest.mark.unit
def test_normal_text_not_formula() -> None:
    text = "本章介绍了数字孪生系统的基本概念和核心能力。"
    assert _is_formula_block(text) is False


@pytest.mark.unit
def test_text_with_isolated_math_char_is_formula() -> None:
    """含有希腊字母 Δ 的短文本被启发式检测为公式（密度触发）。"""
    text = "温度变化范围 ΔT = 25°C，这是一个重要参数。"
    assert _is_formula_block(text) is True


@pytest.mark.unit
def test_inline_math_dollar_detected() -> None:
    """$f(x)=x^2$ 内联数学被检测为公式。"""
    assert _is_formula_block("根据公式 $f(x) = x^2$ 计算") is True


@pytest.mark.unit
def test_greek_letters_high_density() -> None:
    text = "α β γ δ ε ζ η θ ι κ λ μ ν"
    assert _is_formula_block(text) is True
