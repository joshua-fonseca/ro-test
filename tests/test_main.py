import types

import pytest

import main
import scan_once

HEADER = "skin_name,category,rarity,max_price,max_serial,enabled\n"


def _setup(monkeypatch, tmp_path, rows, results, focus=lambda: True):
    """Run main.main() with fake windows modules and scripted scan results; Ctrl+C after the script runs out."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "targets.csv").write_text(HEADER + rows)
    calls, backs = [], []

    def run_once(hwnd, cfg, out, target, navigate_mode, searched, filters_on, snipe=False):
        calls.append((target.skin_name, navigate_mode, searched, filters_on))
        if not results:
            raise KeyboardInterrupt
        return results.pop(0)
    monkeypatch.setattr(scan_once, "_run_once", run_once)
    monkeypatch.setattr("scanner.windows.screen", types.SimpleNamespace(
        find_roblox=lambda: 1, is_focused=lambda h: focus()), raising=False)
    monkeypatch.setattr("scanner.windows.navigate", types.SimpleNamespace(back_to_collection=lambda h: backs.append(1)),
                        raising=False)
    monkeypatch.setattr(main.time, "sleep", lambda s: pytest.fail("the loop must not pause"))
    return calls, backs


def test_one_skin_is_reopened_without_searching_again(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)] * 3)
    assert main.main([]) == 130
    assert [c[:3] for c in calls] == [("Nya Reaper", True, False)] + [("Nya Reaper", True, True)] * 3  # last call is the Ctrl+C


def test_several_skins_are_searched_each_time_and_off_rows_are_skipped(monkeypatch, tmp_path):
    rows = ("Nya Reaper,Knife,Secret,8200,,true\nStarveil AWP,Sniper,Limited,5000,10,true\n"
            "Noir Nya Reaper,Knife,Secret,11800,100,false\n")
    calls, _ = _setup(monkeypatch, tmp_path, rows, [(0, True)] * 3)
    assert main.main([]) == 130
    assert [c[0] for c in calls] == ["Nya Reaper", "Starveil AWP", "Nya Reaper", "Starveil AWP"]
    assert all(not c[2] for c in calls)  # a different skin each time: always searched


def test_three_failures_in_a_row_stop_and_clean_up(monkeypatch, tmp_path, capsys):
    calls, backs = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(1, False)] * 5)
    assert main.main([]) == 1
    assert len(calls) == 3 and len(backs) == 3 and "failed in a row" in capsys.readouterr().out
    assert all(not c[2] for c in calls)  # after a failure the skin is searched again


def test_a_success_resets_the_failure_count(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n",
                      [(1, False), (1, False), (0, True), (1, False), (1, False), (0, True)])
    assert main.main([]) == 130 and len(calls) == 7


def test_nothing_to_scan_is_refused(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,false\n", [])
    assert main.main([]) == 2 and "No enabled skin" in capsys.readouterr().out


def test_cycles_limit_the_passes(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)] * 5)
    assert main.main(["--cycles", "2"]) == 0 and len(calls) == 2


def test_not_focused_at_startup_sends_nothing(monkeypatch, tmp_path, capsys):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)], focus=lambda: False)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    assert main.main(["--wait", "0"]) == 2 and calls == [] and "nothing was sent" in capsys.readouterr().out


def test_losing_focus_pauses_instead_of_failing(monkeypatch, tmp_path):
    state = {"focused": True}
    calls, backs = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(2, False)] * 4 + [(0, True)],
                          focus=lambda: state["focused"])
    sleeps = []

    def sleep(s):  # the user comes back after a few half-seconds
        sleeps.append(s)
        state["focused"] = len(sleeps) >= 3
    monkeypatch.setattr(main.time, "sleep", sleep)
    real = scan_once._run_once

    def run_once(*a):
        out = real(*a)
        state["focused"] = False  # alt-tab during the scan
        return out
    monkeypatch.setattr(scan_once, "_run_once", run_once)
    assert main.main([]) == 130
    assert len(calls) > 3 and backs == []  # four lost-focus scans did not stop the loop or click anything


def test_a_failed_scan_makes_the_next_pass_search_again(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(1, True), (0, True)])
    assert main.main([]) == 130
    assert [c[2] for c in calls] == [False, False, True]  # (1, True) is a failure: not "still searched"


def test_a_scan_that_crashes_counts_as_a_failure_and_the_loop_goes_on(monkeypatch, tmp_path):
    calls, backs = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)])
    real = scan_once._run_once
    state = {"n": 0}

    def crash_first(*a):
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("a card read blew up")
        return real(*a)
    monkeypatch.setattr(scan_once, "_run_once", crash_first)
    assert main.main([]) == 130
    assert backs == [1] and [c[2] for c in calls] == [False, True]  # cleaned up and searched again; the next good scan reopens


def test_clear_matches_flag_clears_before_scanning(monkeypatch, tmp_path, capsys):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)])
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "matches.csv").write_text("x")
    assert main.main(["--clear-matches"]) == 130
    assert not (tmp_path / "output" / "matches.csv").exists() and "Cleared matches.csv" in capsys.readouterr().out


def test_each_full_loop_is_announced(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [(0, True)] * 2)
    assert main.main(["--cycles", "2"]) == 0
    out = capsys.readouterr().out
    assert "Loop 1 done, trying again" in out and "Loop 2 done\n" in out


def test_the_filter_buttons_are_clicked_only_when_the_category_or_rarity_changes(monkeypatch, tmp_path):
    rows = ("A,Knife,Limited,1,,true\nB,Knife,Limited,1,,true\nC,Knife,Secret,1,,true\nD,Sniper,Secret,1,,true\n"
            "E,Sniper,Secret,1,,true\n")
    calls, _ = _setup(monkeypatch, tmp_path, rows, [(0, True)] * 3 + [(1, True)] + [(0, True)] * 2)
    assert main.main([]) == 130
    assert [c[3] for c in calls[:6]] == [False, True, False, False, False, False]  # B repeats A; D failed, so E clicks again


def test_width_and_height_run_the_resize_script_first(monkeypatch, tmp_path):
    calls, _ = _setup(monkeypatch, tmp_path, "Nya Reaper,Knife,Secret,8200,,true\n", [])
    ran = []
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **k: ran.append(cmd) or types.SimpleNamespace(returncode=0))
    assert main.main(["--width", "1600"]) == 130
    assert ran[0][-2:] == ["-Width", "1600"] and ran[0][0] == "powershell.exe" and "resize_roblox.ps1" in ran[0][5]
    ran.clear(); calls.clear()
    monkeypatch.setattr(main.subprocess, "run", lambda cmd, **k: ran.append(cmd) or types.SimpleNamespace(returncode=1))
    assert main.main(["--height", "900"]) == 2 and calls == []  # a failed resize scans nothing
    ran.clear(); main.main([]); assert ran == []  # no size asked for: the script is not run
