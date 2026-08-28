from __future__ import annotations

import io
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from cogs import permission_guard
from utils import command_permissions, proof_service

ROOT = Path(__file__).resolve().parents[1]


def _image_bytes(*, variant: int = 0) -> bytes:
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 600, 320), outline="black", width=5)
    draw.rectangle((80, 90, 300, 150), fill="gray")
    draw.rectangle((350, 90, 560, 150), fill="black" if variant == 0 else "gray")
    if variant:
        draw.rectangle((80, 210, 560, 260), fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class ProofVerificationTests(unittest.TestCase):
    def test_schema_is_additive_and_keeps_member_data_outside_proof_tables(self):
        for table in ("proof_settings", "proof_references", "proof_verifications", "proof_fingerprints"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", proof_service.SCHEMA)
        self.assertNotIn("DELETE FROM levels", proof_service.SCHEMA)
        self.assertNotIn("DELETE FROM economy", proof_service.SCHEMA)

    def test_fingerprint_is_stable_and_detects_difference(self):
        first = proof_service.fingerprint_image(_image_bytes())
        same = proof_service.fingerprint_image(_image_bytes())
        other = proof_service.fingerprint_image(_image_bytes(variant=1))
        self.assertEqual(first.sha256, same.sha256)
        self.assertEqual(first.dhash, same.dhash)
        self.assertEqual(proof_service.hamming_distance(first.dhash, same.dhash), 0)
        self.assertGreater(proof_service.hamming_distance(first.dhash, other.dhash), 0)

    def test_reference_preview_is_compressed_and_recoverable(self):
        encoded = proof_service.compress_preview(_image_bytes())
        decoded = proof_service.preview_bytes(encoded)
        self.assertIsInstance(decoded, bytes)
        self.assertGreater(len(decoded), 100)
        reopened = Image.open(io.BytesIO(decoded))
        self.assertLessEqual(max(reopened.size), 1280)

    def test_decision_accepts_only_strong_distinct_evidence(self):
        analyses = [
            proof_service.CandidateAnalysis(ok=True, score=95, best_reference=0, tampering_risk=5),
            proof_service.CandidateAnalysis(ok=True, score=93, best_reference=1, tampering_risk=8),
        ]
        decision = proof_service.classify(
            analyses,
            required_images=2,
            reference_count=2,
            pass_threshold=88,
            manual_threshold=65,
        )
        self.assertEqual(decision.status, "accepted")
        self.assertGreaterEqual(decision.score, 90)

    def test_same_step_routes_to_manual_when_two_steps_are_required(self):
        analyses = [
            proof_service.CandidateAnalysis(ok=True, score=95, best_reference=0, tampering_risk=5),
            proof_service.CandidateAnalysis(ok=True, score=95, best_reference=0, tampering_risk=5),
        ]
        decision = proof_service.classify(
            analyses,
            required_images=2,
            reference_count=2,
            pass_threshold=88,
            manual_threshold=65,
        )
        self.assertEqual(decision.status, "manual")

    def test_duplicate_is_never_auto_accepted(self):
        decision = proof_service.classify(
            [proof_service.CandidateAnalysis(ok=True, score=100, best_reference=0, tampering_risk=0)],
            required_images=1,
            reference_count=1,
            pass_threshold=88,
            manual_threshold=65,
            duplicate=True,
        )
        self.assertEqual(decision.status, "insufficient")

    def test_low_score_is_insufficient_and_ai_failure_is_manual(self):
        low = proof_service.classify(
            [proof_service.CandidateAnalysis(ok=True, score=25, best_reference=0)],
            required_images=1,
            reference_count=1,
            pass_threshold=88,
            manual_threshold=65,
        )
        fallback = proof_service.classify(
            [proof_service.CandidateAnalysis(ok=False, error="Timeout")],
            required_images=1,
            reference_count=1,
            pass_threshold=88,
            manual_threshold=65,
        )
        self.assertEqual(low.status, "insufficient")
        self.assertEqual(fallback.status, "manual")

    def test_permissions_keep_member_and_admin_proof_commands_separate(self):
        self.assertIn("proof", permission_guard.PROOF_PUBLIC_COMMANDS)
        self.assertIn("proofstatus", permission_guard.PROOF_PUBLIC_COMMANDS)
        self.assertIn("proofsetup", permission_guard.PROOF_ADMIN_COMMANDS)
        self.assertIn("proofreset", permission_guard.PROOF_ADMIN_COMMANDS)
        self.assertIn("proof", command_permissions.PUBLIC_COMMAND_FALLBACKS)
        self.assertEqual(command_permissions.COMMAND_PERMISSION_FALLBACKS["proofsetup"], "administrator")

    def test_runtime_loader_registers_proof_extension(self):
        source = (ROOT / "cogs" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('_PROOF_EXTENSION = "cogs.proof_verification"', source)
        self.assertIn("await _load_proof_verification(bot)", source)


if __name__ == "__main__":
    unittest.main()
