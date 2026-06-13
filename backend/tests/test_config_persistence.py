"""配置健壮性与持久层重启安全测试。"""
import pytest

from app.config import SystemConfig, parse_hms
from app.context import AppContext


def test_clockstart_two_part_accepted_and_normalized(tmp_path):
    cfg = SystemConfig(str(tmp_path / "config.json"))
    cfg.update({"clockStart": "06:00"})          # 两段式不再崩溃
    assert cfg.clockStart == "06:00:00"
    h, m, s = parse_hms(cfg.clockStart)
    assert (h, m, s) == (6, 0, 0)


def test_clockstart_invalid_rejected_without_persist(tmp_path):
    cfg = SystemConfig(str(tmp_path / "config.json"))
    with pytest.raises(ValueError):
        cfg.update({"clockStart": "6点半"})
    assert cfg.clockStart == "06:00:00"          # 坏值未写入


def test_update_is_all_or_nothing(tmp_path):
    cfg = SystemConfig(str(tmp_path / "config.json"))
    before = cfg.FastPower
    with pytest.raises(ValueError):
        cfg.update({"FastPower": 55, "TricklePower": -1})   # 第二项非法
    assert cfg.FastPower == before               # 第一项不应半生效


def test_reset_restores_default_billing_rule(tmp_path):
    ctx = AppContext(str(tmp_path), db_path=str(tmp_path / "c.db"))
    ctx.billing_service.set_parameters({"peak": 9.9, "flat": 9.9, "valley": 9.9})
    assert ctx.billing_service.rule.get_price("peak") == 9.9
    ctx.reset(wipe_history=True)                  # 验收开跑前重置 = 恢复默认费率
    assert ctx.billing_service.rule.get_price("peak") == 1.0
    assert ctx.billing_service.rule.get_service_rate() == 0.8


def test_restart_cancels_zombie_requests(tmp_path):
    db = str(tmp_path / "z.db")
    ctx = AppContext(str(tmp_path), db_path=db)
    ctx.charging_service.submit_request("V1", "T", 40)
    ctx.step()                                    # V1 充电中，落库
    assert ctx.charging_service.query_car_state("V1")["status"] == "CHARGING"
    # 模拟进程重启：同一磁盘库新建 AppContext（内存运行时丢失）
    ctx2 = AppContext(str(tmp_path), db_path=db)
    rows = ctx2.request_repo.find_by_car_id("V1")
    assert rows and rows[0]["status"] == "CANCELED"   # 僵尸"充电中"被清理
