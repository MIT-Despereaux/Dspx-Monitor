from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from core import (
    FridgeReading,
    FridgeState,
    evaluate_fridge_transition,
    evaluate_fridge_faults,
    extract_fridge_reading,
    infer_fridge_state,
)


FIXTURE_DIR = Path(__file__).parent / "data"


def reading(
    mc,
    still,
    four_k,
    pt,
    k4=800,
    k5=800,
    p1=0,
    turbo_speed=0,
    warmup_valves=False,
):
    return FridgeReading(
        mc,
        still,
        four_k,
        pt,
        k4,
        k5,
        p1,
        turbo_speed,
        warmup_valves,
    )


def test_complete_cycle_from_fixture():
    df = pd.read_csv(FIXTURE_DIR / "fridge_cycle.txt", sep="\t")
    state = FridgeState.WARM
    observed = []

    for _, row in df.iterrows():
        result = evaluate_fridge_transition(state, extract_fridge_reading(row))
        assert result.invalid_transition is None
        state = result.state
        observed.append(state)

    assert observed == [
        FridgeState.WARM,
        FridgeState.PT_COOLING_TO_4K,
        FridgeState.PT_COOLING_TO_4K,
        FridgeState.TRANSITION_TO_CONDENSATION,
        FridgeState.CONDENSING,
        FridgeState.DILUTION_COOLING_TO_100_MK,
        FridgeState.OPERATING,
    ]


def test_extract_fridge_reading_includes_alarm_and_warmup_signals():
    current = extract_fridge_reading(pd.Series({
        "full range": 0.05,
        "still": 1.0,
        "Platine 4K": 4.0,
        "PT": 1,
        "K4": 800,
        "K5": 800,
        "P1": 1.2,
        "Pumping turbo speed": 75,
        "VE1": 0,
        "VE2": 0,
        "VE3": 0,
        "VE7": 0,
        "VE22": 1,
        "VE27": 1,
        "VE28": 1,
    }))

    assert current.p1_mbar == 1.2
    assert current.dilution_turbo_speed_pct == 75
    assert current.warmup_valves_configured is True


def test_warm_conditions_reset_from_any_state():
    result = evaluate_fridge_transition(
        FridgeState.OPERATING,
        reading(10, 10, 10, False),
    )

    assert result.state == FridgeState.WARM
    assert result.changed


def test_operating_enters_warming_up_when_pt_is_off_and_valves_are_configured():
    result = evaluate_fridge_transition(
        FridgeState.OPERATING,
        reading(0.24, 1.47, 5.38, False, warmup_valves=True),
    )

    assert result.state == FridgeState.WARMING_UP
    assert result.changed


def test_warming_up_reaches_warm_after_all_stages_exceed_threshold():
    result = evaluate_fridge_transition(
        FridgeState.WARMING_UP,
        reading(10, 10, 10, False, warmup_valves=True),
    )

    assert result.state == FridgeState.WARM


def test_out_of_order_condensation_does_not_change_state():
    result = evaluate_fridge_transition(
        FridgeState.PT_COOLING_TO_4K,
        reading(4, 4, 4, True, k5=2100),
    )

    assert result.state == FridgeState.PT_COOLING_TO_4K
    assert result.invalid_transition


def test_pt_cooling_requires_pt_to_remain_on_until_cooldown_completes():
    result = evaluate_fridge_transition(
        FridgeState.PT_COOLING_TO_4K,
        reading(4, 10, 10, False),
    )

    assert result.state == FridgeState.PT_COOLING_TO_4K
    assert result.invalid_transition


def test_missing_values_do_not_change_state():
    result = evaluate_fridge_transition(
        FridgeState.CONDENSING,
        reading(1, None, 4, True, k5=1000),
    )

    assert result.state == FridgeState.CONDENSING
    assert result.missing_fields == ("still",)


def test_bootstrap_inference_prefers_specific_cold_states():
    assert infer_fridge_state(reading(0.05, 1, 4, True, k5=800)) == FridgeState.OPERATING
    assert infer_fridge_state(reading(1, 1, 4, True, k5=2100)) == FridgeState.CONDENSING
    assert (
        infer_fridge_state(reading(1, 1, 4, False, k5=800))
        == FridgeState.DILUTION_COOLING_TO_100_MK
    )


def test_bootstrap_inference_handles_warm_and_mixed_cooldown():
    assert infer_fridge_state(reading(10, 10, 10, False)) == FridgeState.WARM
    assert infer_fridge_state(reading(10, 10, 10, True)) == FridgeState.PT_COOLING_TO_4K
    assert infer_fridge_state(reading(4, 10, 10, True)) == FridgeState.PT_COOLING_TO_4K


def test_transition_timeout_fault_starts_after_five_hours():
    entered_at = datetime(2026, 1, 1, 0, 0)
    current = reading(4, 4, 4, True)

    assert not evaluate_fridge_faults(
        FridgeState.TRANSITION_TO_CONDENSATION,
        current,
        entered_at,
        entered_at + timedelta(hours=5),
    )
    assert "transition_timeout" in evaluate_fridge_faults(
        FridgeState.TRANSITION_TO_CONDENSATION,
        current,
        entered_at,
        entered_at + timedelta(hours=5, seconds=1),
    )


def test_operating_pressure_fault_uses_either_k4_or_k5():
    now = datetime(2026, 1, 1)

    k4_faults = evaluate_fridge_faults(
        FridgeState.OPERATING,
        reading(0.05, 1, 4, True, k4=901, k5=800),
        now,
        now,
    )
    k5_faults = evaluate_fridge_faults(
        FridgeState.OPERATING,
        reading(0.05, 1, 4, True, k4=800, k5=901),
        now,
        now,
    )

    assert "operating_pressure" in k4_faults
    assert "operating_pressure" in k5_faults


def test_dilution_turbo_p1_fault_is_high_severity_in_every_fridge_state():
    now = datetime(2026, 1, 1)

    for state in FridgeState:
        faults = evaluate_fridge_faults(
            state,
            reading(10, 10, 10, False, p1=1.01, turbo_speed=1),
            now,
            now,
        )

        assert faults["dilution_turbo_p1_high"].severity == "high"


def test_dilution_turbo_p1_fault_requires_turbo_on_and_p1_above_one_mbar():
    now = datetime(2026, 1, 1)

    turbo_off = evaluate_fridge_faults(
        FridgeState.WARM,
        reading(10, 10, 10, False, p1=1.01, turbo_speed=0),
        now,
        now,
    )
    p1_at_limit = evaluate_fridge_faults(
        FridgeState.WARM,
        reading(10, 10, 10, False, p1=1.0, turbo_speed=50),
        now,
        now,
    )

    assert "dilution_turbo_p1_high" not in turbo_off
    assert "dilution_turbo_p1_high" not in p1_at_limit


def test_operating_temperature_faults_use_mc_and_still_thresholds():
    now = datetime(2026, 1, 1)

    mc_faults = evaluate_fridge_faults(
        FridgeState.OPERATING,
        reading(0.501, 1.3, 4, True),
        now,
        now,
    )
    still_faults = evaluate_fridge_faults(
        FridgeState.OPERATING,
        reading(0.5, 1.301, 4, True),
        now,
        now,
    )

    assert "operating_mc_temperature_high" in mc_faults
    assert "operating_still_temperature_high" not in mc_faults
    assert "operating_mc_temperature_high" not in still_faults
    assert "operating_still_temperature_high" in still_faults


def test_operating_temperature_faults_are_inactive_outside_operating_state():
    now = datetime(2026, 1, 1)

    faults = evaluate_fridge_faults(
        FridgeState.DILUTION_COOLING_TO_100_MK,
        reading(0.6, 1.4, 4, True),
        now,
        now,
    )

    assert "operating_mc_temperature_high" not in faults
    assert "operating_still_temperature_high" not in faults


def test_operating_pt_off_fault_has_one_minute_grace_period():
    off_since = datetime(2026, 1, 1, 0, 0)
    current = reading(0.05, 1, 4, False)

    assert "pt_off" not in evaluate_fridge_faults(
        FridgeState.OPERATING,
        current,
        off_since,
        off_since + timedelta(minutes=1),
        off_since,
    )
    assert "pt_off" in evaluate_fridge_faults(
        FridgeState.OPERATING,
        current,
        off_since,
        off_since + timedelta(minutes=1, seconds=1),
        off_since,
    )


def test_pt_off_fault_is_immediate_in_other_cold_states():
    now = datetime(2026, 1, 1, 0, 0)

    faults = evaluate_fridge_faults(
        FridgeState.DILUTION_COOLING_TO_100_MK,
        reading(1, 1, 4, False),
        now,
        now,
        now,
    )

    assert "pt_off" in faults
