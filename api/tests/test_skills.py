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
    text = SkillLibrary.render(matched, how, 9000)
    assert "omitted" not in text
    for skill in matched:
        assert skill.name in text


def test_tech_eval_contract_requires_benchmarks_and_fidelity():
    body = _library().get("tech-eval").body
    for token in ("ARC-e", "CIDEr", "reference_compare", "Batch independent tool calls"):
        assert token in body


def test_sqlite_migration_skill_matches_migration_request():
    names = [skill.name for skill in _library().match("dev", "把 JSON 导出迁移到 SQLite，要求唯一邮箱、外键和幂等")[0]]
    assert "sqlite-migration" in names


def test_file_api_security_skill_matches_hardening_request():
    names = [skill.name for skill in _library().match("dev", "给文件 HTTP API 增加 Bearer 鉴权，阻止路径穿越和符号链接逃逸")[0]]
    assert "file-api-security" in names


def test_new_skills_contain_verification_checklists():
    sqlite = _library().get("sqlite-migration").body
    for token in ("unique", "foreign", "rollback", "idempotent", "PRAGMA integrity_check"):
        assert token.lower() in sqlite.lower()
    files = _library().get("file-api-security").body
    for token in ("Bearer", "realpath", "traversal", "symlink", "401"):
        assert token.lower() in files.lower()
