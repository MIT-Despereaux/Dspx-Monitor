from datetime import datetime, timedelta

import pandas as pd

import scheduler
from core import FridgeReading, FridgeState


def reading(
    mc=0.05,
    still=1,
    four_k=4,
    pt=True,
    k4=800,
    k5=800,
    warmup_valves=False,
):
    return FridgeReading(
        mc,
        still,
        four_k,
        pt,
        k4,
        k5,
        warmup_valves_configured=warmup_valves,
    )


def test_runtime_state_round_trip(tmp_path):
    filepath = tmp_path / "state.json"
    now = datetime(2026, 1, 1, 12, 0)
    runtime = scheduler.FridgeRuntimeState(
        state=FridgeState.OPERATING,
        state_entered_at=now,
        pt_off_since=now - timedelta(minutes=2),
        alarms={
            "pt_off": scheduler.AlarmRecord(
                message="Pulse tube is off",
                successful_sends=2,
                last_sent_at=now - timedelta(minutes=5),
            )
        },
    )

    scheduler.save_fridge_runtime_state(runtime, str(filepath))
    restored = scheduler.load_fridge_runtime_state(str(filepath))

    assert restored == runtime


def test_corrupted_runtime_state_returns_none(tmp_path):
    filepath = tmp_path / "state.json"
    filepath.write_text("{not json", encoding="utf-8")

    assert scheduler.load_fridge_runtime_state(str(filepath)) is None


def test_alarm_spacing_and_three_message_cap():
    now = datetime(2026, 1, 1, 12, 0)
    record = scheduler.AlarmRecord(message="fault")

    assert scheduler.alarm_is_due(record, now)
    record.successful_sends = 1
    record.last_sent_at = now
    assert not scheduler.alarm_is_due(record, now + timedelta(minutes=4, seconds=59))
    assert scheduler.alarm_is_due(record, now + timedelta(minutes=5))
    record.successful_sends = 3
    assert not scheduler.alarm_is_due(record, now + timedelta(hours=1))


def test_recovery_resets_alarm_record():
    now = datetime(2026, 1, 1, 12, 0)
    runtime = scheduler.FridgeRuntimeState(
        FridgeState.OPERATING,
        now,
        alarms={
            "operating_pressure": scheduler.AlarmRecord(
                "Operating pressure is above 900 mbar",
                successful_sends=3,
                last_sent_at=now,
            )
        },
    )

    runtime, faults, _ = scheduler.update_fridge_runtime(runtime, reading(), now)

    assert not faults
    assert "operating_pressure" not in runtime.alarms


def test_changing_pressure_value_does_not_reset_alarm_count():
    now = datetime(2026, 1, 1, 12, 0)
    runtime = scheduler.FridgeRuntimeState(
        FridgeState.OPERATING,
        now,
        alarms={
            "operating_pressure": scheduler.AlarmRecord(
                "Operating pressure is above 900 mbar: K4=901.00 mbar",
                successful_sends=2,
                last_sent_at=now,
            )
        },
    )

    runtime, _, _ = scheduler.update_fridge_runtime(
        runtime,
        reading(k4=950),
        now + timedelta(minutes=1),
    )

    assert runtime.alarms["operating_pressure"].successful_sends == 2


def test_intended_warmup_clears_operating_alarms_and_suppresses_pt_fault():
    now = datetime(2026, 6, 12, 16, 33, 18)
    runtime = scheduler.FridgeRuntimeState(
        FridgeState.OPERATING,
        now - timedelta(days=1),
        pt_off_since=now - timedelta(seconds=30),
        alarms={
            "operating_mc_temperature_high": scheduler.AlarmRecord("MC high"),
        },
    )

    runtime, faults, transition = scheduler.update_fridge_runtime(
        runtime,
        reading(mc=0.243, still=1.468, four_k=5.38, pt=False, warmup_valves=True),
        now,
    )

    assert transition.state == FridgeState.WARMING_UP
    assert runtime.state == FridgeState.WARMING_UP
    assert runtime.pt_off_since is None
    assert not faults
    assert not runtime.alarms


def test_unintended_operating_pt_shutdown_still_alarms_after_grace_period():
    now = datetime(2026, 6, 12, 16, 33, 18)
    runtime = scheduler.FridgeRuntimeState(
        FridgeState.OPERATING,
        now - timedelta(days=1),
        pt_off_since=now - timedelta(minutes=1, seconds=1),
    )

    runtime, faults, transition = scheduler.update_fridge_runtime(
        runtime,
        reading(pt=False, warmup_valves=False),
        now,
    )

    assert transition.state == FridgeState.OPERATING
    assert "pt_off" in faults


def test_failed_alarm_delivery_does_not_increment_count(monkeypatch, tmp_path):
    now = datetime(2026, 1, 1, 12, 0)
    df = pd.DataFrame([{
        "full range": 0.05,
        "still": 1,
        "Platine 4K": 4,
        "PT": 1,
        "K4": 901,
        "K5": 800,
    }])
    scheduler.fridge_runtime_state = scheduler.FridgeRuntimeState(FridgeState.OPERATING, now)
    monkeypatch.setattr(scheduler, "get_files_for_last_24_hours", lambda: ["fixture"])
    monkeypatch.setattr(scheduler, "load_multiple_files", lambda files, logger: df)
    monkeypatch.setattr(scheduler, "FRIDGE_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(scheduler, "_send_state_message", lambda title, message, sent_at: False)

    runtime = scheduler.check_fridge_state(now)

    assert runtime.alarms["operating_pressure"].successful_sends == 0
    assert runtime.alarms["operating_pressure"].last_sent_at is None


def test_successful_alarm_delivery_increments_count(monkeypatch, tmp_path):
    now = datetime(2026, 1, 1, 12, 0)
    df = pd.DataFrame([{
        "full range": 0.05,
        "still": 1,
        "Platine 4K": 4,
        "PT": 1,
        "K4": 901,
        "K5": 800,
    }])
    scheduler.fridge_runtime_state = scheduler.FridgeRuntimeState(FridgeState.OPERATING, now)
    monkeypatch.setattr(scheduler, "get_files_for_last_24_hours", lambda: ["fixture"])
    monkeypatch.setattr(scheduler, "load_multiple_files", lambda files, logger: df)
    monkeypatch.setattr(scheduler, "FRIDGE_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(scheduler, "_send_state_message", lambda title, message, sent_at: True)

    runtime = scheduler.check_fridge_state(now)

    assert runtime.alarms["operating_pressure"].successful_sends == 1
    assert runtime.alarms["operating_pressure"].last_sent_at == now


def test_high_severity_alarm_uses_high_severity_slack_title(monkeypatch, tmp_path):
    now = datetime(2026, 1, 1, 12, 0)
    df = pd.DataFrame([{
        "full range": 10,
        "still": 10,
        "Platine 4K": 10,
        "PT": 0,
        "K4": 800,
        "K5": 800,
        "P1": 1.1,
        "Pumping turbo speed": 50,
    }])
    sent_titles = []
    scheduler.fridge_runtime_state = scheduler.FridgeRuntimeState(FridgeState.WARM, now)
    monkeypatch.setattr(scheduler, "get_files_for_last_24_hours", lambda: ["fixture"])
    monkeypatch.setattr(scheduler, "load_multiple_files", lambda files, logger: df)
    monkeypatch.setattr(scheduler, "FRIDGE_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(
        scheduler,
        "_send_state_message",
        lambda title, message, sent_at: sent_titles.append(title) or True,
    )

    scheduler.check_fridge_state(now)

    assert sent_titles == ["HIGH SEVERITY Fridge Alarm"]
