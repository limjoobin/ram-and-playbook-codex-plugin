from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from admin_bootstrap.bundle import Bundle  # noqa: E402


BUNDLE_ROOT = ROOT / "context-models" / "management-agenda" / "v1"


def generic_observation(
    memory_id: str,
    state_id: str,
    status: str,
    sequence: int,
    locator: str,
) -> dict:
    return {
        "id": memory_id,
        "text": f"Greenhouse ventilation state is {status}",
        "attributes": {
            "schema_version": "organizational-state-v3",
            "state_id": state_id,
            "state_kind": "decision",
            "lifecycle_status": status,
            "evidence_role": "creates",
            "subject": "Greenhouse ventilation mode",
            "project_id": "project-orion-greenhouse",
            "project_step_id": "project-step-orion-validation",
            "meeting_id": "meeting-orion-validation",
            "accountable_entity_id": "employee-river-engineer",
            "related_entity_ids": [],
            "observed_at": "2032-07-19T00:00:00Z",
            "event_sequence": sequence,
            "source_offset_ms": 0,
            "effective_at": "",
            "due_at": "",
            "resolved_at": "",
            "requested_decision": "",
            "impact": "",
            "supersedes_state_ids": [],
            "relations": {"edges": []},
            "source_artifact_id": f"orion-artifact-{memory_id}",
            "source_revision": "revision-zeta",
            "evidence_locator": locator,
        },
    }


def generic_policy() -> dict:
    return {
        "policyId": "orion-generic-temporal-policy-v1",
        "historicalLocatorSequences": [
            {"locatorContains": "Discovery Meeting", "eventSequence": 3}
        ],
        "matchRules": [],
        "families": [
            {
                "stateFamilyId": "project-orion-decision-ventilation",
                "memberStateIds": [
                    "project-orion-decision-ventilation-proposal",
                    "project-orion-decision-ventilation-final",
                ],
            }
        ],
        "relationPolicy": {
            "allowedPredicates": [
                "fulfills",
                "resolves",
                "supersedes",
                "blocks",
                "depends_on",
                "conflicts_with",
                "supports",
            ],
            "confirmationStatus": "confirmed",
            "lifecycleEffects": [],
            "derivedRelations": [],
        },
    }


class ProjectorReusabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = Bundle.load(BUNDLE_ROOT)
        cls.projector = staticmethod(cls.bundle.projector())

    def test_projector_source_contains_no_demo_corpus_identity(self):
        source = (BUNDLE_ROOT / "projector.py").read_text(encoding="utf-8").casefold()

        for forbidden in (
            "project-ami",
            "ami-es",
            "real reaction",
            "es2002",
            "kick-off",
            "kickoff",
        ):
            self.assertNotIn(forbidden, source)

    def test_source_envelope_order_wins_over_an_earlier_meeting_heading(self):
        earlier = generic_observation(
            "orion-earlier",
            "project-orion-decision-ventilation-proposal",
            "proposed",
            7,
            "Validation notes",
        )
        later = generic_observation(
            "orion-later",
            "project-orion-decision-ventilation-final",
            "decided",
            42,
            "Final summary: decisions referenced from Discovery Meeting",
        )

        projections = self.projector([later, earlier], generic_policy())

        self.assertEqual(len(projections), 1)
        current = projections[0].attributes
        self.assertEqual(current["state_id"], "project-orion-decision-ventilation")
        self.assertEqual(current["current_memory_id"], "orion-later")
        self.assertEqual(current["event_sequence"], 42)
        self.assertEqual(current["lifecycle_status"], "decided")

    def test_heading_order_is_only_a_policy_fallback_when_envelope_order_is_unknown(self):
        undated = generic_observation(
            "orion-undated",
            "project-orion-decision-ventilation-proposal",
            "proposed",
            0,
            "Discovery Meeting follow-up",
        )

        projection = self.projector([undated], generic_policy())[0]

        self.assertEqual(projection.attributes["event_sequence"], 3)


if __name__ == "__main__":
    unittest.main()
