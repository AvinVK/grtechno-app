"""Warn before a duplicate material is created (kohal, 2026-11-14: "Nipple 25mm and 25mm nipple is same" - "when you add a material, or type one in the
request picker, the app warns 'A similar material already exists: 25mm Nipple (MAT-0101)' ... even spelling diff a little bit or spacing should be
taken care").

Plain text matching, no model. Two names are compared in steps:
  1. Tidy both: lowercase, split "25mm" into "25" and "mm", count mm/MM and inch/inches/" (and pcs/psc/piece...) as the same word, drop punctuation.
  2. The numbers must be the same - "Nipple 25mm" is never flagged against "Nipple 50mm", however alike the words are.
  3. The words are compared with their spaces and order ignored ("Gatevalve" = "Gate valve", "25mm Nipple" = "Nipple 25mm"), tolerating small spelling
     slips ("Niple"), and the best of a few ways of comparing is the score.
Only a warning: the person can still go ahead, since a needless warning costs a tap and a missed duplicate costs a messy stock list."""

import difflib
import re

from flask import Blueprint, jsonify, request

from .models import Material
from .validation import api_errors

bp = Blueprint("material_match", __name__)
api_errors(bp)

THRESHOLD = 0.75        # a score from 0 to 1; this much alike or more is worth a warning
MIN_LENGTH = 3

_UNITS = {"millimeter": "mm", "millimetre": "mm", "millimeters": "mm", "millimetres": "mm", "inches": "inch", "in": "inch", "pcs": "pc", "psc": "pc",
          "piece": "pc", "pieces": "pc", "mtr": "m", "mtrs": "m", "meter": "m", "metre": "m", "meters": "m", "metres": "m", "kgs": "kg"}


def _tokens(name: str) -> list:
    s = name.lower().replace('"', " inch ").replace("'", " ")
    s = re.sub(r"(\d)([a-z])", r"\1 \2", s)                 # 25mm -> 25 mm
    s = re.sub(r"([a-z])(\d)", r"\1 \2", s)                 # nipple25 -> nipple 25
    s = re.sub(r"[^a-z0-9. ]+", " ", s)
    return [_UNITS.get(t, t) for t in s.split()]


def _is_number(token: str) -> bool:
    return token.replace(".", "").isdigit()


def _parts(name: str):
    tokens = _tokens(name)
    return [t for t in tokens if not _is_number(t)], sorted(t for t in tokens if _is_number(t))


def _trigrams(text: str) -> set:
    text = text if len(text) >= 3 else text + "  "
    return {text[i:i + 3] for i in range(len(text) - 2)}


def similarity(a: str, b: str) -> float:
    """0 to 1: how alike two material names are (see the module docstring); 0 when their numbers differ or either has no words."""
    words_a, numbers_a = _parts(a)
    words_b, numbers_b = _parts(b)
    if numbers_a != numbers_b or not words_a or not words_b:
        return 0.0
    sorted_a, sorted_b = "".join(sorted(words_a)), "".join(sorted(words_b))
    in_order = difflib.SequenceMatcher(None, "".join(words_a), "".join(words_b)).ratio()      # spacing ignored, order kept
    reordered = difflib.SequenceMatcher(None, sorted_a, sorted_b).ratio()                       # spacing and order ignored
    grams_a, grams_b = _trigrams(sorted_a), _trigrams(sorted_b)
    overlap = 2 * len(grams_a & grams_b) / (len(grams_a) + len(grams_b))                        # letters shared, wherever they sit
    return max(in_order, reordered, overlap)


def similar_materials(name: str, exclude_id=None, limit: int = 3) -> list:
    """The materials in stock whose names look like `name`, most alike first."""
    name = (name or "").strip()
    if len(name) < MIN_LENGTH:
        return []
    found = []
    for m in Material.query.filter_by(is_active=True).all():
        if m.id == exclude_id:
            continue
        score = similarity(name, m.name)
        if score >= THRESHOLD:
            found.append((score, m))
    found.sort(key=lambda x: (-x[0], x[1].name.lower()))
    return [{"id": m.id, "code": m.code, "name": m.name, "unit": m.unit, "stock_qty": float(m.stock_qty), "score": round(score, 2)} for score, m in found[:limit]]


@bp.get("/api/materials/similar")
def similar():
    return jsonify(matches=similar_materials(request.args.get("name", "")[:120], request.args.get("exclude_id", type=int)))
