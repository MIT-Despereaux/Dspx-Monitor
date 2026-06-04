from pathlib import Path

import pandas as pd

from core import (
    FridgeReading,
    FridgeState,
    evaluate_fridge_transition,
    extract_fridge_reading,
    infer_fridge_state,
)


FIXTURE_DIR = Path(__file__).parent / "data"


def reading(mc, still, four_k, pt, k4=800, k5=800):
    return FridgeReading(mc, still, four_k, pt, k4, k5)


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


def test_warm_conditions_reset_from_any_state():
    result = evaluate_fridge_transition(
        FridgeState.OPERATING,
        reading(10, 10, 10, False),
    )

    assert result.state == FridgeState.WARM
    assert result.changed


def test_out_of_order_condensation_does_not_change_state():
    result = evaluate_fridge_transition(
        FridgeState.PT_COOLING_TO_4K,
        reading(4, 4, 4, True, k5=2100),
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
