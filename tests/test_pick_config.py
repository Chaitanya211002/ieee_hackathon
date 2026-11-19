"""Mode selection for scripts/start_m5.sh: two laptops when WIN answers, else M5 only."""

import importlib.util
import sys

import pytest

from backend.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("pick_config", REPO_ROOT / "scripts" / "pick_config.py")
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    tracked = tmp_path / "config.yaml"
    text = (REPO_ROOT / "backend" / "config.yaml").read_text()
    tracked.write_text(text.replace("win_hostname: laptop-8k7cobtd.local", "win_hostname: no-such-host-benchlog.local"))
    monkeypatch.setattr(pc, "TRACKED", tracked)
    monkeypatch.setattr(pc, "LOCAL", tmp_path / "data" / "config.local.yaml")
    monkeypatch.setattr(pc, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["pick_config.py"])
    return tmp_path


def test_no_win_anywhere_gives_single_laptop(env, capsys):
    pc.main()
    assert capsys.readouterr().out.strip() == str(pc.TRACKED)
    assert not pc.LOCAL.exists()


def test_stale_local_address_falls_back_to_single_laptop(env, capsys):
    pc.write_local("http://127.0.0.1:9")  # nothing listens there
    pc.main()
    out = capsys.readouterr()
    assert out.out.strip() == str(pc.TRACKED) and "does not answer" in out.err


def test_win_answering_gives_two_laptops_and_refreshes_local(env, capsys, monkeypatch):
    pc.write_local("http://10.0.0.5:8001")
    pc.LOCAL.write_text(pc.LOCAL.read_text() + "\n# stale extra line\n")
    monkeypatch.setattr(pc, "healthy", lambda url, timeout: url == "http://10.0.0.5:8001")
    pc.main()
    assert capsys.readouterr().out.strip() == str(pc.LOCAL)
    text = pc.LOCAL.read_text()
    assert "service: http://10.0.0.5:8001}" in text and "stale extra line" not in text


def test_rediscovers_win_after_address_change(env, capsys, monkeypatch):
    pc.write_local("http://10.0.0.5:8001")  # old address
    monkeypatch.setattr(pc, "resolve", lambda host, timeout: "10.0.0.9")
    monkeypatch.setattr(pc, "healthy", lambda url, timeout: url == "http://10.0.0.9:8001")
    pc.main()
    assert capsys.readouterr().out.strip() == str(pc.LOCAL)
    assert "service: http://10.0.0.9:8001}" in pc.LOCAL.read_text()


def test_solo_flag(env, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pick_config.py", "--solo"])
    monkeypatch.setattr(pc, "healthy", lambda url, timeout: pytest.fail("--solo must not probe WIN"))
    pc.main()
    assert capsys.readouterr().out.strip() == str(pc.TRACKED)
