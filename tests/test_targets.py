import logging

from scanner.logic.models import Target, load_targets

HEADER = "skin_name,category,rarity,max_price,max_serial,enabled\n"


def write(tmp_path, body):
    p = tmp_path / "targets.csv"
    p.write_text(HEADER + body)
    return str(p)


def test_loads_valid_rows_and_blank_means_none(tmp_path):
    path = write(tmp_path, "Nocturne Marlin [Rainbow],Sniper,Secret,9000,500,true\n"
                           "Starveil AWP,Knife,Limited,,,false\n")
    assert load_targets(path) == [
        Target("Nocturne Marlin [Rainbow]", "Sniper", "Secret", 9000, 500, True),
        Target("Starveil AWP", "Knife", "Limited", None, None, False),
    ]


def test_any_case_and_the_short_forms_scrt_ltd_t_f_are_accepted(tmp_path):
    p = tmp_path / "targets.csv"
    p.write_text("Skin_Name,CATEGORY,Rarity,max_price,max_serial,ENABLED\n"
                 "A,sniper,SCRT,100,,T\nB,KNIFE,ltd,100,,f\nC,Knife,Secret,100,,True\nD,Sniper,LIMITED,100,,FALSE\n")
    assert [(t.category, t.rarity, t.enabled) for t in load_targets(str(p))] == [
        ("Sniper", "Secret", True), ("Knife", "Limited", False), ("Knife", "Secret", True), ("Sniper", "Limited", False)]


def test_invalid_rows_are_skipped_with_warning(tmp_path, caplog):
    path = write(tmp_path, "A,Glove,Secret,1,,true\n"        # bad category
                           "B,Sniper,Rare,1,,true\n"          # bad rarity
                           "C,Sniper,Secret,abc,,true\n"      # bad price
                           "D,Sniper,Secret,-1,,true\n"       # negative price
                           "F,Sniper,Secret,1,,maybe\n"       # bad bool
                           ",Sniper,Secret,1,,true\n"         # empty name
                           "Good,Sniper,Secret,1,,true\n")
    with caplog.at_level(logging.WARNING):
        result = load_targets(path)
    assert [t.skin_name for t in result] == ["Good"]
    assert len(caplog.records) == 6


def test_duplicate_skin_keeps_first(tmp_path):
    path = write(tmp_path, "Dup,Sniper,Secret,100,,true\ndup,Sniper,Secret,999,,true\n")
    assert [(t.skin_name, t.max_price) for t in load_targets(path)] == [("Dup", 100)]


def test_old_file_with_stattrak_column_still_loads(tmp_path):
    p = tmp_path / "targets.csv"
    p.write_text("skin_name,category,rarity,max_price,max_serial,stattrak,enabled\nA,Sniper,Secret,1,,with,true\n")
    assert load_targets(str(p)) == [Target("A", "Sniper", "Secret", 1, None, True)]


def test_loading_does_not_modify_the_file(tmp_path):
    path = write(tmp_path, "Good,Sniper,Secret,1,,true\nbad row\n")
    before = open(path, "rb").read()
    load_targets(path)
    assert open(path, "rb").read() == before


def test_shipped_example_targets_file_loads():
    result = load_targets("sniper_arena_scanner_handoff/targets.csv")
    assert [t.skin_name for t in result] == ["Example Skin"]
    assert result[0].max_price is None and result[0].enabled is False


def test_comment_lines_are_skipped_silently_and_line_numbers_stay_right(tmp_path, caplog):
    path = write(tmp_path, "# knives\n"
                           "  # old,Knife,Secret,1,,true\n"      # a comment with commas is still a comment
                           "\n"
                           "Nya Reaper,Knife,Secret,999,2,true\n"
                           "B,Sniper,Rare,1,,true\n")            # line 6: bad rarity
    with caplog.at_level(logging.WARNING):
        assert [t.skin_name for t in load_targets(path)] == ["Nya Reaper"]
    assert len(caplog.records) == 1 and "line 6" in caplog.text


def test_comments_above_the_header_are_allowed(tmp_path, caplog):
    p = tmp_path / "targets.csv"
    p.write_text("# my targets\n\n" + HEADER + "Nya Reaper,Knife,Secret,999,2,true\nB,Sniper,Rare,1,,true\n")
    with caplog.at_level(logging.WARNING):
        assert [t.skin_name for t in load_targets(str(p))] == ["Nya Reaper"]
    assert "line 5" in caplog.text  # B is on line 5 of the file
