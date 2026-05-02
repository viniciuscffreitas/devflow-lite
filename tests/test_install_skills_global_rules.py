from pathlib import Path

from install_skills import link_skills, link_global_rules  # noqa: F401  (link_skills imported to verify symbol export)


def test_link_global_rules_creates_target(tmp_path: Path):
    src_dir = tmp_path / "repo"
    docs = src_dir / "docs"
    docs.mkdir(parents=True)
    (docs / "global-rules.md").write_text("## a\nA\n")

    target_dir = tmp_path / "installed_docs"
    link_global_rules(src_dir, target_dir)
    assert (target_dir / "global-rules.md").is_file()
    assert (target_dir / "global-rules.md").read_text().startswith("## a")
