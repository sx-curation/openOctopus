from config.management_scoring import SCORING_CONTRACT, build_management_scoring_prompt


def test_management_scoring_contract_declares_expected_outputs():
    outputs = SCORING_CONTRACT["outputs"]

    assert "t_minus_1_commitment_score" in outputs
    assert "t_zero_mention_rate" in outputs
    assert "transparency_score" in outputs
    assert SCORING_CONTRACT["status"] == "interim_llm_active"
    assert outputs["t_minus_1_commitment_score"]["scale"] == "checklist_only"
    assert outputs["t_zero_mention_rate"]["scale"] == "theme_continuity_only"


def test_management_scoring_prompt_mentions_required_scores():
    prompt = build_management_scoring_prompt(
        "AAPL",
        "prior quarter",
        "current quarter",
        {"latest_quarter": {"eps_actual": 1.2, "revenue_actual": 90.0}},
    )

    assert "t_minus_1_commitment_score" in prompt
    assert "t_zero_mention_rate" in prompt
    assert "hard_commitments" in prompt
    assert "forward_guidance" in prompt
    assert "visionary_fluff" in prompt
    assert "direction_consistency" in prompt
    assert '"value": null' in prompt
    assert "AAPL" in prompt
