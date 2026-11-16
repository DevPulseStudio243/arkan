# -*- coding: utf-8 -*-
import os, sys, textwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import config_loader as cl

@pytest.fixture(autouse=True)
def clean(monkeypatch):
    cl._CACHE.clear()
    monkeypatch.delenv(cl.ENV_PATH, raising=False)
    monkeypatch.delenv(cl.ENV_STRICT, raising=False)

def write(tmp_path, text, monkeypatch):
    p = tmp_path / "cfg.yaml"; p.write_text(textwrap.dedent(text), encoding="utf-8")
    monkeypatch.setenv(cl.ENV_PATH, str(p)); return p

LEGACY = """
procurement_margins:
  cables_power: 0.08
  cables_control: 0.10
  cable_trays: 0.05
  conduits_pvc: 0.07
  bare_copper_earthing: 0.10
  lighting_luminaires: 0.02
  accessories_hardware: 0.15
"""

def test_missing_file_gives_neutral_defaults_and_flag(tmp_path, monkeypatch):
    monkeypatch.setenv(cl.ENV_PATH, str(tmp_path / "absent.yaml"))
    cfg = cl.load_project_config()
    assert cfg["project_metadata"]["client"] == ""            # plus de client en dur
    info = cl.get_config_info()
    assert info["source"] == "DEFAULTS" and info["warning"]
    assert cl.resolve_margin("CABLE_TRAY") == (0.0, False)    # aucune marge inventée

def test_missing_file_strict(tmp_path, monkeypatch):
    monkeypatch.setenv(cl.ENV_PATH, str(tmp_path / "absent.yaml")); monkeypatch.setenv(cl.ENV_STRICT, "1")
    with pytest.raises(cl.ConfigError): cl.load_project_config()

def test_invalid_yaml_fails_loudly(tmp_path, monkeypatch):
    write(tmp_path, "procurement_margins: [unclosed", monkeypatch)
    with pytest.raises(cl.ConfigError): cl.load_project_config()

@pytest.mark.parametrize("bad", ["cable_trays: 5", "cable_trays: -0.1", "cable_trays: '8%'", "cable_trays: 0.9"])
def test_margin_bounds(tmp_path, monkeypatch, bad):
    write(tmp_path, "procurement_margins:\n  " + bad + "\n", monkeypatch)
    with pytest.raises(cl.ConfigError): cl.load_project_config()

def test_legacy_keys_still_work(tmp_path, monkeypatch):
    write(tmp_path, LEGACY, monkeypatch)
    assert cl.resolve_margin("CABLE_TRAY") == (0.05, True)
    assert cl.resolve_margin("CABLE") == (0.08, True)
    assert cl.resolve_margin("CABLE", cable_kind="CONTROL") == (0.10, True)

def test_conduit_margin_reachable_for_pull_boxes_regression(tmp_path, monkeypatch):
    """Avant : buses/chambres recevaient 5 % (marge chemins). Maintenant par catégorie."""
    write(tmp_path, LEGACY, monkeypatch)
    assert cl.resolve_margin("BUSE", discipline="CHEMINS_ET_CANALISATIONS") == (0.07, True)
    assert cl.resolve_margin("PULL_BOX", discipline="CHEMINS_ET_CANALISATIONS") == (0.0, True)  # équipement

def test_hardware_margin_now_applied(tmp_path, monkeypatch):
    write(tmp_path, LEGACY, monkeypatch)
    assert cl.resolve_margin("BOLT") == (0.15, True)

def test_unknown_category_is_flagged_not_defaulted(tmp_path, monkeypatch):
    write(tmp_path, LEGACY, monkeypatch)
    assert cl.resolve_margin("PIPE") == (0.0, False)
    write(tmp_path, LEGACY + "  default: 0.05\n", monkeypatch); cl._CACHE.clear()
    assert cl.resolve_margin("PIPE") == (0.05, True)

def test_by_category_overrides_legacy(tmp_path, monkeypatch):
    write(tmp_path, LEGACY + "  by_category: {CABLE_POWER: 0.10}\n", monkeypatch)
    assert cl.resolve_margin("CABLE") == (0.10, True)

def test_apply_margin_units(tmp_path, monkeypatch):
    write(tmp_path, LEGACY, monkeypatch)
    assert cl.apply_margin(100, 0.08, "m") == 108.0
    assert cl.apply_margin(1, 0.05, "EA") == 1.0       # plus de 1 -> 2
    assert cl.apply_margin(3, 0.05, "EA") == 3.0
    assert cl.apply_margin(10, 0.15, "EA") == 12.0     # 1.5 spares -> 2
    assert cl.apply_margin(0, 0.1, "m") == 0.0

def test_ceil_policy_optional(tmp_path, monkeypatch):
    write(tmp_path, LEGACY + "  rounding: {EA: ceil}\n", monkeypatch)
    assert cl.apply_margin(1, 0.05, "EA") == 2.0

def test_reload_on_file_change_and_deepcopy(tmp_path, monkeypatch):
    p = write(tmp_path, LEGACY, monkeypatch)
    c1 = cl.load_project_config(); c1["procurement_margins"]["cable_trays"] = 0.4   # mutation locale
    assert cl.resolve_margin("CABLE_TRAY")[0] == 0.05
    p.write_text(LEGACY.replace("cable_trays: 0.05", "cable_trays: 0.06"), encoding="utf-8")
    os.utime(p, (p.stat().st_mtime + 5, p.stat().st_mtime + 5))
    assert cl.resolve_margin("CABLE_TRAY")[0] == 0.06

def test_info_has_hash_and_schema(tmp_path, monkeypatch):
    write(tmp_path, "schema_version: 2\n" + LEGACY, monkeypatch)
    info = cl.get_config_info()
    assert len(info["sha256"]) == 12 and info["schema_version"] == 2

def test_example_yaml_is_valid(monkeypatch):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setenv(cl.ENV_PATH, os.path.join(here, "project_config.example.yaml"))
    cfg = cl.load_project_config()
    assert cl.resolve_margin("CABLE_TRAY") == (0.05, True)
    assert cfg["project_metadata"]["client"] == ""

def test_real_user_yaml_loads_if_present(monkeypatch):
    p = "/mnt/user-data/uploads/project_config.yaml"
    if not os.path.exists(p): pytest.skip("YAML utilisateur absent")
    monkeypatch.setenv(cl.ENV_PATH, p)
    cl.load_project_config()
    assert cl.resolve_margin("CABLE")[0] == 0.08
    assert cl.resolve_margin("BOLT") == (0.15, True)
