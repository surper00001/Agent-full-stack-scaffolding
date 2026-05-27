"""
RAG 评估模块。

使用 Ragas 框架对检索质量进行量化评估：
- context_recall: 检索到的上下文中是否包含正确答案
- context_precision: 检索到的上下文是否与问题相关
- faithfulness: 生成的回答是否忠实于检索到的上下文

使用方式：
    # 单独运行评估（需要已索引的知识库）
    pytest tests/eval/ -v -m eval

    # 仅验证数据集结构（不需要知识库）
    pytest tests/eval/ -v -m "not eval"
"""
