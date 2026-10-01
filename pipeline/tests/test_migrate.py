import pytest

from pipeline.migrate import Migration, load_migrations, pending


def test_load_migrations_sorts_by_number(tmp_path):
    (tmp_path / "0002_second.sql").write_text("select 2;")
    (tmp_path / "0001_first.sql").write_text("select 1;")
    assert [m.name for m in load_migrations(tmp_path)] == ["0001_first.sql", "0002_second.sql"]


def test_load_migrations_rejects_bad_name(tmp_path):
    (tmp_path / "add_table.sql").write_text("select 1;")
    with pytest.raises(ValueError, match="must look like"):
        load_migrations(tmp_path)


def test_load_migrations_rejects_duplicate_number(tmp_path):
    (tmp_path / "0001_a.sql").write_text("select 1;")
    (tmp_path / "0001_b.sql").write_text("select 2;")
    with pytest.raises(ValueError, match="share the number"):
        load_migrations(tmp_path)


def test_pending_skips_applied():
    first, second = Migration("0001_a.sql", "select 1;"), Migration("0002_b.sql", "select 2;")
    assert pending([first, second], {first.name: first.checksum}) == [second]


def test_pending_rejects_edited_migration():
    m = Migration("0001_a.sql", "select 1;")
    with pytest.raises(ValueError, match="changed after it was applied"):
        pending([m], {m.name: "old-checksum"})


def test_repo_migrations_are_valid():
    assert load_migrations()[0].name == "0001_core.sql"
