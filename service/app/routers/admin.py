"""Admin utilities: backup download, rclone remote push, system status."""
import asyncio
import io
import logging
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.get("/backup")
async def download_backup():
    """Stream a zip of all FoodAssistant app data as a browser download.

    Includes settings.json, the SQLite database, and any user-edited data
    files (staples.txt, etc.). Grocy and Mealie data live in separate
    containers — use scripts/backup.sh on the host to capture everything,
    or push to a cloud remote via the Backup > Push to Remote button.
    """
    zip_bytes, filename = _build_zip()
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _build_zip() -> tuple[bytes, str]:
    """Create the backup zip in memory, return (bytes, filename)."""
    data_dir = Path(settings.data_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if data_dir.exists():
            for f in sorted(data_dir.rglob("*")):
                if f.is_file():
                    arc_name = Path("foodassistant-data") / f.relative_to(data_dir)
                    zf.write(f, arc_name)
    return buf.getvalue(), f"foodassistant-backup-{date.today()}.zip"


@router.post("/backup/remote")
async def push_to_remote():
    """Write the backup zip to disk and push it to the configured rclone remote.

    Requires rclone to be installed in the container and a remote configured
    at the path set in RCLONE_REMOTE (Settings > Security > Backup).
    """
    if not settings.rclone_remote:
        raise HTTPException(400, "No rclone remote configured — set one in Settings > Security > Backup.")
    import shutil
    if not shutil.which("rclone"):
        raise HTTPException(500, "rclone is not installed in this container. Rebuild the image after adding it to the Dockerfile.")

    zip_bytes, filename = _build_zip()
    tmp = Path("/tmp") / filename
    tmp.write_bytes(zip_bytes)
    try:
        dest = settings.rclone_remote.rstrip("/") + "/" + filename
        env = {"RCLONE_CONFIG": str(Path(settings.data_dir) / "rclone.conf")}
        proc = await asyncio.create_subprocess_exec(
            "rclone", "copyto", str(tmp), dest,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**__import__('os').environ, **env},
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            raise HTTPException(502, f"rclone failed: {stderr.decode()[:400]}")
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "message": f"Backup pushed to {settings.rclone_remote}", "filename": filename}


@router.post("/backup/test-remote")
async def test_remote():
    """Test whether rclone can reach the configured remote."""
    if not settings.rclone_remote:
        return {"ok": False, "error": "No rclone remote configured."}
    import shutil
    if not shutil.which("rclone"):
        return {"ok": False, "error": "rclone not found in container. Rebuild image with rclone installed."}
    env = {"RCLONE_CONFIG": str(Path(settings.data_dir) / "rclone.conf")}
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "lsd", settings.rclone_remote,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**__import__('os').environ, **env},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            return {"ok": True, "message": f"Remote reachable: {settings.rclone_remote}"}
        return {"ok": False, "error": stderr.decode()[:300] or "Remote unreachable."}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timed out connecting to remote."}
    except Exception as e:
        return {"ok": False, "error": str(e)}
