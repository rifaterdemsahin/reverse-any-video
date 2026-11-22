"""Projects and job outputs in Azure Blob Storage.

One container holds every project. Each project gets its own folder:

  projects/<slug>/project.json              the project record (name, slug, created)
  projects/<slug>/jobs/<job_id>/<file>      outputs of each analysis run in the project (delivered)
  internal/<job_id>/<file>                  source video and frames, kept for the operator only

The connection string comes from, in order:
  AZURE_STORAGE_CONNECTION_STRING           set directly (local development)
  AZURE_KEYVAULT_URL                        read the secret named by AZURE_STORAGE_SECRET_NAME

Key Vault is read with a service principal (AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET)
or, when those are not set, with DefaultAzureCredential. The Azure SDK is imported only when used,
so the app runs without it.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER", "reverse-any-video")
SECRET_NAME = os.environ.get("AZURE_STORAGE_SECRET_NAME", "reverse-any-video-storage-connection-string")
PREFIX = "projects/"


class StorageError(Exception):
    """Storage is not configured, or an Azure call failed."""


class ProjectExists(StorageError):
    pass


def slugify(name: str) -> str:
    """'My Video Project!' -> 'my-video-project'. Empty result means the name has no usable characters."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def configured() -> bool:
    return bool(os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_KEYVAULT_URL"))


def _connection_string() -> str:
    direct = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if direct:
        return direct
    vault_url = os.environ.get("AZURE_KEYVAULT_URL")
    if not vault_url:
        raise StorageError("Azure storage is not configured (set AZURE_KEYVAULT_URL or AZURE_STORAGE_CONNECTION_STRING).")
    from azure.identity import ClientSecretCredential, DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    tenant, client, secret = (os.environ.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"))
    if tenant and client and secret:
        credential = ClientSecretCredential(tenant, client, secret)
    else:
        credential = DefaultAzureCredential()
    return SecretClient(vault_url=vault_url, credential=credential).get_secret(SECRET_NAME).value


class ProjectStore:
    """Creates projects and saves job outputs. `container` is an azure ContainerClient, or any object with the same methods."""

    def __init__(self, container):
        self.container = container

    @classmethod
    def from_env(cls) -> "ProjectStore":
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(_connection_string())
        container = service.get_container_client(CONTAINER)
        if not container.exists():
            container.create_container()
        return cls(container)

    # ----- projects -----

    def _record_name(self, slug: str) -> str:
        return f"{PREFIX}{slug}/project.json"

    def create_project(self, name: str) -> dict:
        slug = slugify(name)
        if not slug:
            raise ValueError("Project name needs at least one letter or number.")
        if self.get_project(slug) is not None:
            raise ProjectExists(f"A project called '{slug}' already exists.")
        record = {"name": name.strip(), "slug": slug, "created": time.time()}
        self.container.upload_blob(self._record_name(slug), json.dumps(record, indent=2).encode(), overwrite=False)
        return record

    def get_project(self, slug: str) -> dict | None:
        if not re.fullmatch(r"[a-z0-9-]{1,60}", slug or ""):
            return None
        blob = self.container.get_blob_client(self._record_name(slug))
        if not blob.exists():
            return None
        record = json.loads(blob.download_blob().readall())
        record["jobs"] = self.list_jobs(slug)
        return record

    def list_projects(self) -> list[dict]:
        names = [b.name for b in self.container.list_blobs(name_starts_with=PREFIX)
                 if b.name.endswith("/project.json") and b.name.count("/") == 2]
        projects = []
        for name in sorted(names):
            record = json.loads(self.container.get_blob_client(name).download_blob().readall())
            projects.append({"name": record["name"], "slug": record["slug"], "created": record["created"]})
        return projects

    def list_jobs(self, slug: str) -> list[str]:
        base = f"{PREFIX}{slug}/jobs/"
        ids = set()
        for b in self.container.walk_blobs(name_starts_with=base, delimiter="/"):
            if hasattr(b, "name") and b.name.endswith("/"):
                ids.add(b.name[len(base):].rstrip("/"))
        return sorted(ids)

    # ----- internal working files (kept for the operator, never delivered to customers) -----

    def save_internal(self, job_id: str, paths: list[Path]) -> list[str]:
        """Upload working files such as the source video and the frames zip to internal/<job_id>/."""
        saved = []
        for path in paths:
            path = Path(path)
            if not path.exists():
                continue
            blob_name = f"internal/{job_id}/{path.name}"
            with path.open("rb") as f:
                self.container.upload_blob(blob_name, f, overwrite=True)
            saved.append(blob_name)
        return saved

    # ----- outputs -----

    def save_outputs(self, slug: str, job_id: str, out_dir: Path, names: list[str]) -> list[str]:
        """Upload the named files from out_dir into the project's job folder. Returns the blob names."""
        saved = []
        for name in names:
            path = Path(out_dir) / name
            if not path.exists():
                continue
            blob_name = f"{PREFIX}{slug}/jobs/{job_id}/{name}"
            with path.open("rb") as f:
                self.container.upload_blob(blob_name, f, overwrite=True)
            saved.append(blob_name)
        return saved
