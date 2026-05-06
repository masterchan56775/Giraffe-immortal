"""
skill_example.py — 示例技能
演示如何创建一个可被SkillLoader动态加载的技能模块
"""

SKILL_NAME = "example_skill"
SKILL_DESCRIPTION = "示例技能：将文本转为大写"
SKILL_CATEGORY = "text"
SKILL_VERSION = "1.0.0"


def execute(text: str) -> str:
    """将输入文本转为大写。"""
    return text.upper()


def get_metadata() -> dict:
    return {
        "name": SKILL_NAME,
        "description": SKILL_DESCRIPTION,
        "category": SKILL_CATEGORY,
        "version": SKILL_VERSION,
    }
