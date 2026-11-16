from pathlib import Path

from harness.skills import SkillLibrary

API_DIR = Path(__file__).resolve().parent.parent

PROMPT = (
    "目标模型：LLM预训练，VLM预训练，VLA预训练，世界模型预训练，S2S预训练，原生多模态预训练。"
    "单卡 RTX 5060 Ti 16G / L20 48G / H800 80G，总训练时间不超过50小时。"
    "帮我评估一下所需的最小算力资源。参考HTML页面：D:/ref/page.html，输出到 D:/out/eval。"
)


def _library() -> SkillLibrary:
    lib = SkillLibrary(API_DIR / "skills")
    lib.add_dir(API_DIR / "plugins" / "coding" / "skills", "coding")
    return lib


def test_tech_eval_skill_matches_evaluation_request():
    names = [skill.name for skill in _library().match("dev", PROMPT)[0]]
    assert "tech-eval" in names
    assert "web-delivery" in names


def test_render_budget_keeps_matched_skills():
    lib = _library()
    matched, how = lib.match("dev", PROMPT)
    text = SkillLibrary.render(matched, how, 7000)
    assert "omitted" not in text
    for skill in matched:
        assert skill.name in text
