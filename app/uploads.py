"""File uploads: only site-survey photos today, but generic enough for whatever comes next. Stored under
instance/uploads/<subdir>/ - instance/ is already fully git-ignored, so no separate ignore rule is needed.
The uploaded file's own name is never trusted or kept; only its extension survives, and only if it's one
we recognise."""

import secrets

from flask import Blueprint, current_app, send_from_directory
from werkzeug.exceptions import abort

bp = Blueprint("uploads", __name__)

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


class UploadError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def save_upload(file_storage, subdir: str) -> str:
    """Save one uploaded image under instance/uploads/<subdir>/ and return its stored filename."""
    ext = ALLOWED_TYPES.get((file_storage.mimetype or "").lower())
    if not ext:
        raise UploadError("Only JPEG, PNG or WEBP photos are allowed")
    directory = current_app.config["UPLOAD_DIR"] / subdir
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.{ext}"
    file_storage.save(directory / filename)
    return filename


def delete_upload(subdir: str, filename: str) -> None:
    path = current_app.config["UPLOAD_DIR"] / subdir / filename
    path.unlink(missing_ok=True)


@bp.get("/uploads/<subdir>/<filename>")
def serve_upload(subdir, filename):
    """Covered by the app's normal sign-in gate like every other route - no separate auth check needed."""
    directory = current_app.config["UPLOAD_DIR"] / subdir
    if "/" in filename or ".." in filename:
        abort(404)
    return send_from_directory(directory, filename)
