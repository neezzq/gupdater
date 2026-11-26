from gupdater.app import main
from gupdater.demo import SECRET_STEAM_ACCOUNT, SECRET_TOKEN
from gupdater.report import build_report, default_report_name, run_scan


def test_report_lists_launchers_games_and_environment(demo_ctx):
    result = run_scan(demo_ctx)
    text = build_report(result, demo_ctx)
    assert "Компьютер: CLUB-PC-07" in text
    assert "SmartShell: найден" in text
    assert "=== Лаунчеры: найдено 8 из 8, игр: 14 ===" in text
    assert "Dota 2 | id 570 | версия 18690011" in text and "Нужно обновление" in text
    assert "steam: " in text  # launcher protocols
    assert "SmartShell Client" in text
    assert default_report_name(result).startswith("gupdater-otchet-CLUB-PC-07-")


def test_report_has_no_account_names_tokens_or_user_folder(demo_ctx):
    text = build_report(run_scan(demo_ctx), demo_ctx)
    assert SECRET_STEAM_ACCOUNT not in text
    assert "guest_two" not in text
    assert SECRET_TOKEN not in text
    assert demo_ctx.env["USERPROFILE"] not in text
    assert "%USERPROFILE%" in text


def test_command_line_report(tmp_path):
    out = tmp_path / "report.txt"
    assert main(["--demo", "--report", str(out)]) == 0
    assert "GUpdater" in out.read_text(encoding="utf-8-sig")
