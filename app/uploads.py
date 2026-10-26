"""File uploads: only site-survey photos today, but generic enough for whatever comes next. Stored under
instance/uploads/<subdir>/ - instance/ is already fully git-ignored, so no separate ignore rule is needed.
The uploaded file's own name is never trusted or kept; only its extension survives, and only if it's one
we recognise."""

import secrets
import shutil

from flask import Blueprint, current_app, send_from_directory
from werkzeug.exceptions import abort

bp = Blueprint("uploads", __name__)

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
# A bill is as often a scanned PDF as a photo of the paper receipt.
DOCUMENT_TYPES = {**IMAGE_TYPES, "application/pdf": "pdf"}


class UploadError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def save_upload(file_storage, subdir: str, allowed: dict = IMAGE_TYPES) -> str:
    """Save one uploaded file under instance/uploads/<subdir>/ and return its stored filename."""
    ext = allowed.get((file_storage.mimetype or "").lower())
    if not ext:
        kinds = "a JPEG, PNG or WEBP photo" if allowed is IMAGE_TYPES else "a JPEG, PNG, WEBP or PDF file"
        raise UploadError(f"Choose {kinds}")
    directory = current_app.config["UPLOAD_DIR"] / subdir
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.{ext}"
    file_storage.save(directory / filename)
    return filename


def copy_upload(src_subdir: str, filename: str, dst_subdir: str) -> str:
    """Copy a stored file into another upload folder under a fresh name and return that name - so the two
    owners (a lead's document and the project's copy of it) can each delete theirs without touching the other."""
    root = current_app.config["UPLOAD_DIR"]
    new_name = f"{secrets.token_hex(16)}.{filename.rsplit('.', 1)[-1]}"
    (root / dst_subdir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / src_subdir / filename, root / dst_subdir / new_name)
    return new_name


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
