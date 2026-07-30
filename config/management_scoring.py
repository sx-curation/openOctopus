SCORING_CONTRACT = {
    "version": "1.0",
    "status": "interim_llm_active",
    "inputs": {
        "previous_quarter_transcript": "Required for T-1 commitments and prior guidance references.",
        "current_quarter_transcript": "Required for T-0 topic continuity and transparency evaluation.",
        "prepared_remarks": "Preferred management narrative source for commitment extraction.",
        "qa_segments": "Preferred source for transparency / deflection assessment.",
        "current_quarter_actuals": "Required for checking whether prior hard commitments and guidance landed against reported numbers.",
    },
    "outputs": {
        "t_minus_1_commitment_score": {
            "scale": "checklist_only",
            "description": "LLM-built completion checklist of prior-quarter hard commitments and forward guidance against current-quarter actuals.",
        },
        "t_zero_mention_rate": {
            "scale": "theme_continuity_only",
            "description": "LLM comparison of whether the same topics are carried forward with consistent direction, continuity, and sentiment.",
        },
        "transparency_score": {
            "scale": "0-10",
            "description": "Still computed with transcript heuristics; not yet LLM-scored in this interim implementation.",
        },
        "evidence": {
            "type": "list",
            "description": "Supporting transcript snippets with speaker, quarter, and rationale.",
        },
    },
    "guardrails": [
        "Do not fabricate commitments not present in transcript text.",
        "Do not emit numeric fulfillment or mention scores for T-1 or T-0 outputs.",
        "Return unavailable when prior-quarter or current-quarter transcript coverage is missing.",
        "Prefer explicit management language over analyst paraphrases.",
        "Treat visionary fluff as zero-weight narrative unless it becomes a concrete operational commitment.",
    ],
}


def build_management_scoring_prompt(
    ticker: str,
    previous_excerpt: str,
    current_excerpt: str,
    actuals_snapshot: dict,
) -> str:
    return f"""
You are evaluating management credibility for {ticker}.

Task:
1. Classify prior-quarter management statements into:
   - hard_commitments: concrete commitments with explicit timelines or numeric targets
   - forward_guidance: forecast ranges, directional guidance, or qualitative outlook statements
     (e.g. "we expect continued growth", "margins will remain stable", "demand remains strong")
   - visionary_fluff: strategic narrative with no concrete path or measurable target
2. Build t_minus_1_commitment_score as a checklist, not a score:
   compare prior-quarter hard commitments and forward guidance against current-quarter reported actuals,
   and mark each item as met, missed, mixed, or unverifiable.
3. Build t_zero_mention_rate as a same-topic continuity review, not a score:
   compare the prior-quarter commitments/guidance set with the current-quarter transcript, and judge
   whether the direction is aligned, mixed, or diverged; whether the topic was continued, updated, or dropped;
   and whether management tone is positive, neutral, or negative.
4. Be inclusive: include qualitative forward guidance (e.g. "we expect strong demand") as forward_guidance items,
   not just explicit numeric targets. Mark their outcome as "unverifiable" if no direct comparison is possible.
   Always try to extract at least 2-3 forward_guidance items from the prior quarter transcript.
   Only return empty arrays if the transcript truly contains zero forward-looking statements.

Output requirements:
- Return structured JSON only.
- Use this schema exactly:
  {{
    "t_minus_1_commitment_score": {{
      "value": null,
      "rationale": "...",
      "evidence": ["..."],
      "hard_commitments": [
        {{
          "statement": "...",
          "topic": "...",
          "metric": "eps|revenue|margin|dividend|other",
          "timeframe": "...",
          "verifiable": true,
          "outcome": "met|missed|mixed|unverifiable",
          "comparison_basis": "...",
          "actual_reference": "..."
        }}
      ],
      "forward_guidance": [
        {{
          "statement": "...",
          "topic": "...",
          "direction": "up|down|stable|range|other",
          "timeframe": "...",
          "verifiable": true,
          "outcome": "met|missed|mixed|unverifiable",
          "comparison_basis": "...",
          "actual_reference": "..."
        }}
      ],
      "visionary_fluff": []
    }},
    "t_zero_mention_rate": {{
      "value": null,
      "rationale": "...",
      "evidence": ["..."],
      "matches": [
        {{
          "topic": "...",
          "previous_statement": "...",
          "current_reference": "...",
          "repeat_status": "repeated|updated|not_revisited",
          "direction_consistency": "aligned|mixed|diverged",
          "topic_continuity": "continued|updated|dropped",
          "sentiment": "positive|neutral|negative",
          "deviation_note": "..."
        }}
      ]
    }}
  }}
- Include evidence snippets for each score.
- If transcript coverage is insufficient, return unavailable with reasons instead of guessing.
- Ignore analyst questions unless management explicitly adopts the point.

Prior-quarter transcript excerpt:
{previous_excerpt}

Current-quarter transcript excerpt:
{current_excerpt}

Current-quarter reported actual snapshot:
{actuals_snapshot}
""".strip()
