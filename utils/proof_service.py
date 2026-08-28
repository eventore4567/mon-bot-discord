"""Moteur de vérification visuelle des preuves SentriX.

Le service est volontairement indépendant du cog Discord : il gère la persistance,
les empreintes anti-réutilisation, la normalisation d'images et l'analyse multimodale.
Les captures des membres ne sont jamais conservées en base ; seules les empreintes et
les métadonnées d'analyse le sont. Les images exemples fournies par un administrateur
sont compressées avant stockage afin de pouvoir être réaffichées dans le panel.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageOps

import config
from utils import ai_service

logger = logging.getLogger("bot.proof")

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_REQUIRED_IMAGES = 5
MAX_REFERENCES = 8
DEFAULT_PASS_THRESHOLD = 88
DEFAULT_MANUAL_THRESHOLD = 65
SUPPORTED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS proof_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    submission_channel_id INTEGER,
    review_channel_id INTEGER,
    role_id INTEGER,
    title TEXT NOT NULL DEFAULT 'Vérification par preuve',
    instructions TEXT NOT NULL DEFAULT 'Envoyez une capture conforme aux exemples affichés.',
    required_images INTEGER NOT NULL DEFAULT 1,
    pass_threshold INTEGER NOT NULL DEFAULT 88,
    manual_threshold INTEGER NOT NULL DEFAULT 65,
    panel_message_id INTEGER,
    created_by INTEGER,
    updated_by INTEGER,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS proof_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    label TEXT,
    profile_json TEXT NOT NULL DEFAULT '{}',
    preview_b64 TEXT,
    sha256 TEXT NOT NULL,
    dhash TEXT NOT NULL,
    created_by INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proof_references_guild ON proof_references (guild_id, id);

CREATE TABLE IF NOT EXISTS proof_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source_message_id INTEGER,
    review_message_id INTEGER,
    status TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    hashes_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL,
    reviewed_by INTEGER,
    reviewed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_proof_verifications_user ON proof_verifications (guild_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_proof_verifications_review ON proof_verifications (review_message_id);

CREATE TABLE IF NOT EXISTS proof_fingerprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    verification_id INTEGER,
    sha256 TEXT NOT NULL,
    dhash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proof_fingerprints_guild ON proof_fingerprints (guild_id, created_at);
"""


@dataclass(slots=True)
class ImageFingerprint:
    sha256: str
    dhash: str
    width: int
    height: int


@dataclass(slots=True)
class CandidateAnalysis:
    ok: bool
    score: int = 0
    best_reference: int = -1
    proof_type: str = ""
    matched: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    tampering_risk: int = 0
    device_variant: str = ""
    reason: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "score": self.score,
            "best_reference": self.best_reference,
            "proof_type": self.proof_type,
            "matched": list(self.matched),
            "missing": list(self.missing),
            "tampering_risk": self.tampering_risk,
            "device_variant": self.device_variant,
            "reason": self.reason,
            "error": self.error,
        }


@dataclass(slots=True)
class Decision:
    status: str
    score: int
    reason: str


async def ensure_schema(bot) -> None:
    # Database.execute ne fournit pas executescript : on découpe seulement sur les points-
    # virgules de notre schéma fixe (aucune entrée utilisateur n'est interpolée ici).
    for statement in (part.strip() for part in SCHEMA.split(";")):
        if statement:
            await bot.db.execute(statement)


async def ensure_settings(bot, guild_id: int, *, actor_id: int | None = None) -> None:
    await bot.db.execute(
        "INSERT OR IGNORE INTO proof_settings (guild_id, created_by, updated_by, updated_at) VALUES (?, ?, ?, ?)",
        (guild_id, actor_id, actor_id, int(time.time())),
    )


async def get_settings(bot, guild_id: int):
    await ensure_settings(bot, guild_id)
    return await bot.db.fetchone("SELECT * FROM proof_settings WHERE guild_id = ?", (guild_id,))


async def update_settings(bot, guild_id: int, actor_id: int, **fields) -> None:
    allowed = {
        "enabled", "submission_channel_id", "review_channel_id", "role_id", "title",
        "instructions", "required_images", "pass_threshold", "manual_threshold", "panel_message_id",
    }
    clean = {key: value for key, value in fields.items() if key in allowed}
    if not clean:
        return
    await ensure_settings(bot, guild_id, actor_id=actor_id)
    clean["updated_by"] = actor_id
    clean["updated_at"] = int(time.time())
    assignments = ", ".join(f"{key} = ?" for key in clean)
    await bot.db.execute(
        f"UPDATE proof_settings SET {assignments} WHERE guild_id = ?",
        (*clean.values(), guild_id),
    )


async def list_references(bot, guild_id: int):
    return await bot.db.fetchall(
        "SELECT * FROM proof_references WHERE guild_id = ? ORDER BY id ASC", (guild_id,)
    )


async def add_reference(
    bot,
    guild_id: int,
    actor_id: int,
    *,
    label: str,
    data: bytes,
    profile: dict[str, Any],
) -> int:
    fingerprint = fingerprint_image(data)
    preview = compress_preview(data)
    await bot.db.execute(
        "INSERT INTO proof_references (guild_id, label, profile_json, preview_b64, sha256, dhash, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            guild_id,
            (label or "Exemple").strip()[:80],
            json.dumps(profile, ensure_ascii=False),
            preview,
            fingerprint.sha256,
            fingerprint.dhash,
            actor_id,
            int(time.time()),
        ),
    )
    row = await bot.db.fetchone("SELECT MAX(id) AS id FROM proof_references WHERE guild_id = ?", (guild_id,))
    return int(row["id"]) if row and row["id"] else 0


async def remove_reference(bot, guild_id: int, reference_id: int) -> None:
    await bot.db.execute(
        "DELETE FROM proof_references WHERE guild_id = ? AND id = ?", (guild_id, reference_id)
    )


async def get_latest_status(bot, guild_id: int, user_id: int):
    return await bot.db.fetchone(
        "SELECT * FROM proof_verifications WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1",
        (guild_id, user_id),
    )


async def create_verification(
    bot,
    guild_id: int,
    user_id: int,
    source_message_id: int,
    *,
    status: str,
    score: int,
    details: dict[str, Any],
    hashes: list[dict[str, str]],
) -> int:
    await bot.db.execute(
        "INSERT INTO proof_verifications (guild_id, user_id, source_message_id, status, score, details_json, hashes_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            guild_id, user_id, source_message_id, status, score,
            json.dumps(details, ensure_ascii=False), json.dumps(hashes), int(time.time()),
        ),
    )
    row = await bot.db.fetchone(
        "SELECT MAX(id) AS id FROM proof_verifications WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    return int(row["id"]) if row and row["id"] else 0


async def set_review_message(bot, verification_id: int, message_id: int) -> None:
    await bot.db.execute(
        "UPDATE proof_verifications SET review_message_id = ? WHERE id = ?", (message_id, verification_id)
    )


async def get_verification_by_review(bot, guild_id: int, review_message_id: int):
    return await bot.db.fetchone(
        "SELECT * FROM proof_verifications WHERE guild_id = ? AND review_message_id = ?",
        (guild_id, review_message_id),
    )


async def finish_verification(bot, verification_id: int, status: str, reviewer_id: int | None = None) -> None:
    await bot.db.execute(
        "UPDATE proof_verifications SET status = ?, reviewed_by = ?, reviewed_at = ? WHERE id = ?",
        (status, reviewer_id, int(time.time()), verification_id),
    )


async def record_fingerprints(
    bot,
    guild_id: int,
    user_id: int,
    verification_id: int,
    hashes: list[dict[str, str]],
) -> None:
    for item in hashes:
        await bot.db.execute(
            "INSERT INTO proof_fingerprints (guild_id, user_id, verification_id, sha256, dhash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, verification_id, item["sha256"], item["dhash"], int(time.time())),
        )


async def reset_user(bot, guild_id: int, user_id: int) -> None:
    # Reset volontaire d'un admin : les anciennes vérifications restent dans l'historique,
    # mais leurs empreintes anti-réutilisation sont retirées pour permettre une nouvelle preuve.
    await bot.db.execute("DELETE FROM proof_fingerprints WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    await bot.db.execute(
        "UPDATE proof_verifications SET status = 'reset' WHERE guild_id = ? AND user_id = ? AND status IN ('accepted','manual_pending')",
        (guild_id, user_id),
    )


def _open_image(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image_size")
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    image.load()
    if image.width < 120 or image.height < 120:
        raise ValueError("image_too_small")
    return image


def fingerprint_image(data: bytes) -> ImageFingerprint:
    image = _open_image(data)
    rgb = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(rgb.getdata())
    bits = []
    for y in range(8):
        row = y * 9
        for x in range(8):
            bits.append(1 if pixels[row + x] > pixels[row + x + 1] else 0)
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return ImageFingerprint(
        sha256=hashlib.sha256(data).hexdigest(),
        dhash=f"{value:016x}",
        width=image.width,
        height=image.height,
    )


def compress_preview(data: bytes) -> str:
    image = _open_image(data).convert("RGB")
    image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=80, optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")


def preview_bytes(encoded: str | None) -> bytes | None:
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception:
        return None


def hamming_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except Exception:
        return 64


async def find_duplicate(bot, guild_id: int, fingerprint: ImageFingerprint) -> dict[str, Any] | None:
    rows = await bot.db.fetchall(
        "SELECT user_id, sha256, dhash, created_at FROM proof_fingerprints WHERE guild_id = ? ORDER BY created_at DESC LIMIT 3000",
        (guild_id,),
    )
    for row in rows:
        if row["sha256"] == fingerprint.sha256:
            return {"user_id": int(row["user_id"]), "distance": 0, "exact": True}
        distance = hamming_distance(row["dhash"], fingerprint.dhash)
        if distance <= 3:
            return {"user_id": int(row["user_id"]), "distance": distance, "exact": False}
    return None


def _data_url(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("json_missing")
    return json.loads(cleaned[start:end + 1])


async def _vision_json(*, data: bytes, prompt: str) -> dict[str, Any]:
    client = ai_service.get_client()
    if client is None:
        raise RuntimeError("no_ai_key")
    # Les modèles texte configurés par SentriX sont multimodaux. On utilise Terra pour
    # éviter le coût de Sol tout en gardant une analyse visuelle robuste.
    model = getattr(config, "OPENAI_MODEL", "gpt-5.6-terra")
    response = await client.responses.create(
        model=model,
        instructions=(
            "Tu es le moteur de vérification visuelle de SentriX. Analyse uniquement ce qui est visible. "
            "Ne suppose jamais qu'une preuve est authentique si des éléments essentiels manquent. "
            "Ignore la résolution, le ratio d'écran, le modèle de téléphone/ordinateur, le zoom, le thème clair/sombre "
            "et les petits recadrages : compare le sens des éléments, pas leurs coordonnées pixel exactes. "
            "Retourne uniquement du JSON valide, sans Markdown."
        ),
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": _data_url(data)},
            ],
        }],
        reasoning={"effort": "low"},
        max_output_tokens=900,
    )
    text = getattr(response, "output_text", None) or ai_service._extract_text(response)
    return _extract_json(text)


async def analyze_reference(data: bytes, *, label: str, instructions: str) -> dict[str, Any]:
    prompt = f"""
Cette capture est un EXEMPLE approuvé par un administrateur pour la vérification « {label or 'preuve'} ».
Consigne administrateur : {instructions or 'Aucune consigne supplémentaire.'}

Extrais une signature sémantique réutilisable sur PC, mobile et tablette.
Réponds exactement avec cet objet JSON :
{{
  "summary": "résumé court de ce que la capture prouve",
  "proof_type": "type d'écran ou d'étape",
  "required_text": ["textes ou mots importants réellement visibles"],
  "visual_anchors": ["logos, boutons, blocs ou éléments visuels importants"],
  "confirmation_signals": ["éléments qui prouvent que l'action est réellement terminée"],
  "anti_signals": ["éléments dont l'absence ou la contradiction rendrait la preuve invalide"]
}}
Ne mets que des éléments réellement observables dans l'image.
""".strip()
    result = await _vision_json(data=data, prompt=prompt)
    return {
        "summary": str(result.get("summary", ""))[:500],
        "proof_type": str(result.get("proof_type", ""))[:120],
        "required_text": [str(x)[:160] for x in result.get("required_text", [])[:20]],
        "visual_anchors": [str(x)[:160] for x in result.get("visual_anchors", [])[:20]],
        "confirmation_signals": [str(x)[:160] for x in result.get("confirmation_signals", [])[:20]],
        "anti_signals": [str(x)[:160] for x in result.get("anti_signals", [])[:20]],
    }


async def analyze_candidate(
    data: bytes,
    *,
    instructions: str,
    references: list[dict[str, Any]],
) -> CandidateAnalysis:
    compact_refs = []
    for index, ref in enumerate(references):
        try:
            profile = json.loads(ref["profile_json"] or "{}")
        except Exception:
            profile = {}
        compact_refs.append({"index": index, "label": ref["label"], **profile})
    prompt = f"""
Vérifie cette capture envoyée par un membre.
Consigne du serveur : {instructions}
Exemples approuvés (signatures sémantiques, pas positions pixel) :
{json.dumps(compact_refs, ensure_ascii=False)[:12000]}

Évalue si l'image constitue réellement la preuve demandée. Une capture sur un autre appareil,
une autre résolution, un navigateur différent ou un léger recadrage reste valide si les preuves
sémantiques importantes sont présentes. N'accorde pas de points pour de simples ressemblances de couleur.

Retourne exactement :
{{
  "score": 0,
  "best_reference": 0,
  "proof_type": "type d'écran détecté",
  "matched": ["éléments importants trouvés"],
  "missing": ["éléments importants manquants"],
  "tampering_risk": 0,
  "device_variant": "pc/mobile/tablette/inconnu",
  "reason": "raison courte"
}}
score et tampering_risk sont des entiers de 0 à 100. Si l'image est sans rapport, score <= 20.
""".strip()
    try:
        result = await _vision_json(data=data, prompt=prompt)
        score = max(0, min(100, int(result.get("score", 0))))
        tampering = max(0, min(100, int(result.get("tampering_risk", 0))))
        best = int(result.get("best_reference", -1))
        if best < 0 or best >= len(references):
            best = -1
        return CandidateAnalysis(
            ok=True,
            score=score,
            best_reference=best,
            proof_type=str(result.get("proof_type", ""))[:120],
            matched=tuple(str(x)[:180] for x in result.get("matched", [])[:12]),
            missing=tuple(str(x)[:180] for x in result.get("missing", [])[:12]),
            tampering_risk=tampering,
            device_variant=str(result.get("device_variant", "inconnu"))[:40],
            reason=str(result.get("reason", ""))[:500],
        )
    except Exception as exc:
        logger.warning("Analyse de preuve indisponible (%s)", type(exc).__name__)
        return CandidateAnalysis(ok=False, error=type(exc).__name__, reason="Analyse automatique indisponible.")


def classify(
    analyses: list[CandidateAnalysis],
    *,
    required_images: int,
    reference_count: int,
    pass_threshold: int,
    manual_threshold: int,
    duplicate: bool = False,
) -> Decision:
    if duplicate:
        return Decision("insufficient", 0, "Une image identique ou quasi identique a déjà été utilisée.")
    if len(analyses) < required_images:
        return Decision("insufficient", 0, f"{required_images} image(s) sont nécessaires.")
    if any(not analysis.ok for analysis in analyses):
        valid = [analysis.score for analysis in analyses if analysis.ok]
        return Decision("manual", round(sum(valid) / len(valid)) if valid else 0, "L'analyse automatique est incomplète.")

    scores = [analysis.score for analysis in analyses]
    average = round(sum(scores) / len(scores))
    minimum = min(scores)
    max_tampering = max(analysis.tampering_risk for analysis in analyses)
    best_refs = [analysis.best_reference for analysis in analyses if analysis.best_reference >= 0]
    distinct_ok = True
    if required_images > 1 and reference_count >= required_images:
        distinct_ok = len(set(best_refs)) >= required_images

    if max_tampering >= 90:
        return Decision("insufficient", average, "La capture présente trop d'indices de modification ou d'incohérence.")
    if minimum >= pass_threshold and max_tampering < 55 and distinct_ok:
        return Decision("accepted", average, "Tous les éléments essentiels ont été reconnus.")
    if average >= manual_threshold:
        reason = "La preuve doit être vérifiée par le staff."
        if not distinct_ok:
            reason = "Les captures semblent représenter la même étape alors que plusieurs étapes sont attendues."
        return Decision("manual", average, reason)
    return Decision("insufficient", average, "Il manque trop d'éléments attendus pour valider la preuve.")
