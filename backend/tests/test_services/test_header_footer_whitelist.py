"""页眉/页脚白名单 is_likely_noise_in_header_footer 单元测试。"""

import pytest

from src.services.document_processors.layout import is_likely_noise_in_header_footer


@pytest.mark.unit
def test_empty_string_is_noise() -> None:
    assert is_likely_noise_in_header_footer("", 1) is True
    assert is_likely_noise_in_header_footer("   ", 2) is True


@pytest.mark.unit
def test_pure_page_number_is_noise() -> None:
    assert is_likely_noise_in_header_footer("42", 1) is True
    assert is_likely_noise_in_header_footer("  123  ", 2) is True


@pytest.mark.unit
def test_chinese_page_number_is_noise() -> None:
    assert is_likely_noise_in_header_footer("第 5 页", 1) is True


@pytest.mark.unit
def test_english_page_number_is_noise() -> None:
    assert is_likely_noise_in_header_footer("Page 3 of 10", 2) is True
    assert is_likely_noise_in_header_footer("Page 12", 3) is True


@pytest.mark.unit
def test_url_is_noise() -> None:
    assert is_likely_noise_in_header_footer("https://example.com/doc", 2) is True


@pytest.mark.unit
def test_confidential_mark_is_noise() -> None:
    assert is_likely_noise_in_header_footer("Confidential", 2) is True
    assert is_likely_noise_in_header_footer("DRAFT", 3) is True


@pytest.mark.unit
def test_version_string_is_noise() -> None:
    assert is_likely_noise_in_header_footer("Version 1.2.3", 2) is True


@pytest.mark.unit
def test_chapter_title_whitelist() -> None:
    """章节标题不应被识别为噪声。"""
    assert is_likely_noise_in_header_footer("第三章 系统架构设计", 1) is False
    assert is_likely_noise_in_header_footer("3.1 数据采集模块", 5) is False


@pytest.mark.unit
def test_english_section_whitelist() -> None:
    assert is_likely_noise_in_header_footer("Introduction", 2) is False
    assert is_likely_noise_in_header_footer("Related Work", 3) is False
    assert is_likely_noise_in_header_footer("Conclusion", 10) is False


@pytest.mark.unit
def test_long_text_whitelist() -> None:
    """长文本（>40 字符）视为正文，不标记为噪声。"""
    long_text = "本系统采用微服务架构设计，通过容器化部署实现了高可用性和弹性伸缩能力。"
    assert is_likely_noise_in_header_footer(long_text, 2) is False


@pytest.mark.unit
def test_chinese_complete_sentence_whitelist() -> None:
    """含中文标点的完整句子 → 保留。"""
    text = "本文提出了一种新的数字孪生建模方法。"
    assert is_likely_noise_in_header_footer(text, 3) is False


@pytest.mark.unit
def test_page_with_content_mixed_not_noise() -> None:
    """页码+附加内容混合格式保留。"""
    assert is_likely_noise_in_header_footer("42 / 结论", 2) is False


@pytest.mark.unit
def test_short_text_in_header_zone_page1_passive() -> None:
    """短文本在第 1 页 → 保守保留（不判定为噪声）。"""
    assert is_likely_noise_in_header_footer("ACME Corp", 1) is False


@pytest.mark.unit
def test_short_text_in_header_zone_later_page_is_noise() -> None:
    """短文本在第 2+ 页 → 保守判定为噪声。"""
    assert is_likely_noise_in_header_footer("ACME Corp", 3) is True


@pytest.mark.unit
def test_copyright_is_noise() -> None:
    assert is_likely_noise_in_header_footer("© 2024 ACME Corp", 2) is True
