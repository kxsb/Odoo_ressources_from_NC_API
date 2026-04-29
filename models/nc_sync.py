from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import time
import tempfile
from datetime import datetime, timezone
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from urllib.error import HTTPError

from odoo import api, models

_logger = logging.getLogger(__name__)


class RessourcesNcSync(models.AbstractModel):
    _name = "ressources.nc.sync"
    _description = "Sync Nextcloud ressource Index"

    # =========================
    # CONFIG
    # =========================

    def _get_icp(self):
        return self.env["ir.config_parameter"].sudo()

    def _get_base_url(self) -> str:
        return self._get_icp().get_param("ressources_from_nc_api.base_url", "").rstrip("/")

    def _get_username(self) -> str:
        return self._get_icp().get_param("ressources_from_nc_api.username", "")

    def _get_password(self) -> str:
        return self._get_icp().get_param("ressources_from_nc_api.app_password", "")

    def _get_root_path(self) -> str:
        return self._get_icp().get_param(
            "ressources_from_nc_api.root_path",
            "/Centre de ressources",
        )

    def _get_storage_dir(self) -> str:
        data_dir = self._get_icp().get_param("data_dir")
        if not data_dir:
            data_dir = "/var/lib/odoo"
        path = os.path.join(data_dir, "ressources_from_nc_api")
        os.makedirs(path, exist_ok=True)
        return path

    def _get_private_json_path(self) -> str:
        return os.path.join(self._get_storage_dir(), "index_private.json")

    def _get_auto_create_file_shares(self) -> bool:
        value = self._get_icp().get_param(
            "ressources_from_nc_api.auto_create_file_shares",
            "1",
        )
        return value.strip().lower() not in ("0", "false", "no", "off", "")

    def _get_share_create_delay_seconds(self) -> float:
        value = self._get_icp().get_param(
            "ressources_from_nc_api.share_create_delay_seconds",
            "1.2",
        )
        try:
            return max(0.0, float(value))
        except ValueError:
            return 1.2

    def _get_share_create_limit(self) -> int:
        """
        Limite de sécurité par synchro.
        0 = aucune limite.
        Utile pour éviter de créer 500 liens d'un coup par erreur.
        """
        value = self._get_icp().get_param(
            "ressources_from_nc_api.share_create_limit",
            "0",
        )
        try:
            return max(0, int(value))
        except ValueError:
            return 0

    def _count_files_recursive(self, node: dict[str, Any]) -> int:
        count = 0

        for child in node.get("children", []):
            if child.get("type") == "file":
                count += 1
            elif child.get("type") == "directory":
                count += self._count_files_recursive(child)

        return count

    def _flatten_directories(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        result = []

        if node.get("type") == "directory":
            result.append(node)

        for child in node.get("children", []):
            if child.get("type") == "directory":
                result.extend(self._flatten_directories(child))

        return result

    # =========================
    # Contrôle des droits
    # =========================

    def _upsert_folders_from_tree(self, tree: dict[str, Any]):
        Folder = self.env["ressources.nc.folder"].sudo()

        directories = self._flatten_directories(tree)

        existing = {
            rec.relative_path: rec
            for rec in Folder.search([])
        }

        to_create = []
        to_update = []

        for directory in directories:
            rel = directory.get("relative_path") or ""

            if not rel:
                continue
            parent = directory.get("parent_relative_path") or ""
            name = directory.get("name") or ""
            file_count = self._count_files_recursive(directory)

            if rel in existing:
                rec = existing[rel]
                to_update.append((rec, {
                    "name": name,
                    "parent_path": parent,
                    "file_count": file_count,
                }))
            else:
                to_create.append({
                    "name": name,
                    "relative_path": rel,
                    "parent_path": parent,
                    "file_count": file_count,
                    "visibility": "network",
                })

        if to_create:
            Folder.create(to_create)

        for rec, vals in to_update:
            rec.write(vals)

        current_paths = {
            directory.get("relative_path")
            for directory in directories
            if directory.get("relative_path")
        }

        if current_paths:
            obsolete = Folder.search([
                ("relative_path", "not in", list(current_paths)),
                ("active", "=", True),
            ])

            if obsolete:
                _logger.info(
                    "NC sync: archivage de %s dossier(s) obsolète(s) dans ressources.nc.folder.",
                    len(obsolete),
                )
                obsolete.write({"active": False})
        else:
            _logger.warning(
                "NC sync: aucun dossier trouvé, skip archivage pour éviter une purge massive."
            )

    # =========================
    # HELPERS
    # =========================

    def _auth_header(self) -> str:
        token = f"{self._get_username()}:{self._get_password()}".encode("utf-8")
        return "Basic " + base64.b64encode(token).decode("ascii")

    def _quote_path(self, path: str) -> str:
        return quote(path, safe="/")

    def _normalize_posix(self, path: str) -> str:
        return path.replace("\\", "/")

    def _iso_from_http_date(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).isoformat(timespec="seconds")
        except Exception:
            return None

    def _guess_mime(self, filename: str) -> str | None:
        mime, _ = mimetypes.guess_type(filename)
        return mime

    def _human_size(self, num_bytes: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(num_bytes)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{num_bytes} B"

    def _category_from_rel_path(self, rel_path: str) -> str | None:
        pure = PurePosixPath(rel_path)
        return pure.parts[0] if pure.parts else None

    def _build_search_text(self, item: dict[str, Any]) -> str:
        parts = [
            item.get("name", ""),
            item.get("relative_path", ""),
            item.get("parent_relative_path", ""),
            item.get("category", "") or "",
            item.get("extension", "") or "",
            item.get("mime_type", "") or "",
        ]
        return " | ".join(part for part in parts if part).lower()

    # =========================
    # HTTP / XML
    # =========================

    def _http_json(self, url: str) -> dict[str, Any]:
        req = Request(url, method="GET")
        req.add_header("Authorization", self._auth_header())
        req.add_header("OCS-APIRequest", "true")
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=120) as resp:
                return json.load(resp)

        except HTTPError as e:
            _logger.error(
                "NC sync: erreur HTTP JSON %s sur %s",
                e.code,
                url,
            )
            raise

    def _http_propfind(self, url: str, body: str, depth: str = "infinity") -> bytes:
        req = Request(url, method="PROPFIND", data=body.encode("utf-8"))
        req.add_header("Authorization", self._auth_header())
        req.add_header("Depth", depth)
        req.add_header("Content-Type", "application/xml; charset=utf-8")

        try:
            with urlopen(req, timeout=300) as resp:
                return resp.read()

        except HTTPError as e:
            _logger.error(
                "NC sync: erreur HTTP PROPFIND %s sur %s",
                e.code,
                url,
            )
            raise

    # =========================
    # NEXTCLOUD API
    # =========================

    def _fetch_public_shares(self) -> tuple[dict[str, str], dict[str, str]]:
        """
        Retourne :
        - folder_shares : relative_path -> public_url
        - file_shares   : relative_path -> public_url

        Récupère les partages publics OCS sans filtre path, puis filtre côté Python
        sur root_path. Inclut une protection si Nextcloud ignore offset.
        """
        base_url = self._get_base_url()
        root_path = self._normalize_posix(unquote(self._get_root_path())).rstrip("/")
        root_posix = PurePosixPath(root_path)

        folder_shares: dict[str, str] = {}
        file_shares: dict[str, str] = {}

        limit = 200
        offset = 0
        previous_counts = (-1, -1)

        while True:
            query = urlencode({
                "format": "json",
                "limit": limit,
                "offset": offset,
            })

            url = f"{base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares?{query}"
            payload = self._http_json(url)

            data = payload.get("ocs", {}).get("data", [])
            if isinstance(data, dict):
                data = [data]

            if not data:
                break

            for item in data:
                if item.get("share_type") != 3:
                    continue

                path_str = item.get("path")
                share_url = item.get("url")
                item_type = item.get("item_type")

                if not path_str or not share_url:
                    continue

                path_str = self._normalize_posix(unquote(path_str)).rstrip("/")

                try:
                    relative = PurePosixPath(path_str).relative_to(root_posix)
                except ValueError:
                    continue

                rel_str = self._normalize_posix(str(relative)).rstrip("/")
                if rel_str == ".":
                    rel_str = ""

                if item_type == "file":
                    file_shares[rel_str] = share_url
                elif item_type in ("folder", "dir"):
                    folder_shares[rel_str] = share_url

            current_counts = (len(folder_shares), len(file_shares))

            if len(data) < limit:
                break

            if current_counts == previous_counts:
                _logger.warning(
                    "NC sync: pagination stoppée — aucune nouvelle entrée à offset=%s "
                    "(Nextcloud ignore peut-être offset)",
                    offset,
                )
                break

            previous_counts = current_counts
            offset += limit

            _logger.info(
                "NC sync: pagination partages — offset=%s, dossiers=%s, fichiers=%s",
                offset,
                len(folder_shares),
                len(file_shares),
            )

        _logger.info(
            "NC sync: partages publics récupérés — dossiers=%s, fichiers=%s",
            len(folder_shares),
            len(file_shares),
        )

        return folder_shares, file_shares

    def _create_public_share(self, nc_path: str) -> str:
        base_url = self._get_base_url()
        url = f"{base_url}/ocs/v2.php/apps/files_sharing/api/v1/shares"

        data = urlencode({
            "path": nc_path,
            "shareType": 3,
        }).encode("utf-8")

        req = Request(url, method="POST", data=data)
        req.add_header("Authorization", self._auth_header())
        req.add_header("OCS-APIRequest", "true")
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urlopen(req, timeout=120) as resp:
                payload = json.load(resp)

        except HTTPError as e:
            if e.code == 429:
                raise RuntimeError("NEXTCLOUD_RATE_LIMIT") from e
            raise

        meta = payload.get("ocs", {}).get("meta", {})
        if meta.get("statuscode") not in (100, 200):
            raise ValueError(f"Création partage refusée pour {nc_path}: {meta}")

        public_url = payload.get("ocs", {}).get("data", {}).get("url")
        if not public_url:
            raise ValueError(f"Aucune URL publique retournée pour {nc_path}")

        return public_url

    def _scan_remote_tree(self) -> list[dict[str, Any]]:
        """
        Scan distant via WebDAV PROPFIND sur tout l'arbre.
        On récupère uniquement les métadonnées.
        """
        base_url = self._get_base_url()
        username = self._get_username()
        root_path = self._get_root_path()

        quoted_username = quote(username, safe="")
        dav_url = (
            f"{base_url}/remote.php/dav/files/{quoted_username}"
            f"{self._quote_path(root_path)}"
        )

        body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
  <d:prop>
    <d:resourcetype/>
    <d:getcontentlength/>
    <d:getcontenttype/>
    <d:getlastmodified/>
    <oc:fileid/>
  </d:prop>
</d:propfind>"""

        raw = self._http_propfind(dav_url, body, depth="infinity")
        root = ET.fromstring(raw)

        ns = {
            "d": "DAV:",
            "oc": "http://owncloud.org/ns",
        }

        root_posix = PurePosixPath(root_path)
        items: list[dict[str, Any]] = []

        for response in root.findall("d:response", ns):
            href = response.findtext("d:href", default="", namespaces=ns)
            propstat = next(
                (
                    ps for ps in response.findall("d:propstat", ns)
                    if "200" in (ps.findtext("d:status", "", namespaces=ns) or "")
                ),
                None,
            )
            if propstat is None:
                continue

            prop = propstat.find("d:prop", ns)
            if prop is None:
                continue

            resource_type = prop.find("d:resourcetype", ns)
            is_dir = resource_type is not None and resource_type.find("d:collection", ns) is not None

            content_length = prop.findtext("d:getcontentlength", default="0", namespaces=ns)
            content_type = prop.findtext("d:getcontenttype", default="", namespaces=ns)
            last_modified = prop.findtext("d:getlastmodified", default="", namespaces=ns)
            file_id = prop.findtext("oc:fileid", default="", namespaces=ns)

            dav_prefix = f"/remote.php/dav/files/{quoted_username}"

            try:
                path_part = href.split(dav_prefix, 1)[1]
            except IndexError:
                _logger.warning("Href WebDAV ignoré, préfixe inattendu: %s", href)
                continue

            path_part = unquote(path_part)
            path_part = self._normalize_posix(path_part).rstrip("/")
            pure = PurePosixPath(path_part)

            try:
                relative = pure.relative_to(root_posix)
            except ValueError:
                continue

            rel_str = self._normalize_posix(str(relative)).rstrip("/")
            if rel_str in ("", "."):
                items.append({
                    "type": "directory",
                    "name": root_posix.name,
                    "relative_path": "",
                    "parent_relative_path": "",
                    "size_bytes": 0,
                    "mime_type": None,
                    "modified_at": self._iso_from_http_date(last_modified),
                    "file_id": file_id or None,
                })
                continue

            items.append({
                "type": "directory" if is_dir else "file",
                "name": PurePosixPath(rel_str).name,
                "relative_path": rel_str,
                "parent_relative_path": self._normalize_posix(str(PurePosixPath(rel_str).parent)).rstrip("/")
                if str(PurePosixPath(rel_str).parent) != "."
                else "",
                "size_bytes": int(content_length or 0) if not is_dir else 0,
                "mime_type": None if is_dir else (content_type or self._guess_mime(rel_str)),
                "modified_at": self._iso_from_http_date(last_modified),
                "file_id": file_id or None,
            })

        return items

    # =========================
    # INDEX BUILD
    # =========================

    def _get_auto_create_folder_shares(self) -> bool:
        value = self._get_icp().get_param(
            "ressources_from_nc_api.auto_create_folder_shares",
            "1",
        )
        return value.strip().lower() not in ("0", "false", "no", "off", "")

    def _ensure_missing_folder_shares(
        self,
        remote_items: list[dict[str, Any]],
        folder_shares: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, int]]:
        """
        Crée les liens publics manquants pour les dossiers.

        On ignore la racine relative "" pour éviter de partager tout le dossier racine
        par accident. On ne partage que les sous-dossiers.
        """
        if not self._get_auto_create_folder_shares():
            _logger.info("NC sync: création automatique des liens dossiers désactivée.")
            return dict(folder_shares), {
                "existing": len(folder_shares),
                "created": 0,
                "missing": 0,
                "errors": 0,
                "limited": 0,
            }

        root_path = self._get_root_path().rstrip("/")
        delay = self._get_share_create_delay_seconds()
        limit = self._get_share_create_limit()

        updated = dict(folder_shares)

        folder_items = [
            item for item in remote_items
            if item.get("type") == "directory" and item.get("relative_path")
        ]

        created = 0
        missing = 0
        errors = 0
        limited = 0

        for item in folder_items:
            rel_path = item["relative_path"]

            if rel_path in updated:
                continue

            if limit and created >= limit:
                limited += 1
                continue

            missing += 1
            nc_path = f"{root_path}/{rel_path}".replace("//", "/")

            try:
                public_url = self._create_public_share(nc_path)

            except RuntimeError as e:
                if str(e) == "NEXTCLOUD_RATE_LIMIT":
                    errors += 1
                    safe_delay = max(delay, 30)

                    _logger.warning(
                        "NC sync: rate limit Nextcloud détecté pour %s. Pause %ss puis arrêt du batch.",
                        rel_path,
                        safe_delay,
                    )

                    time.sleep(safe_delay)
                    break

                raise

            except Exception as e:
                errors += 1
                _logger.warning(
                    "NC sync: impossible de créer le partage pour %s: %s",
                    rel_path,
                    e,
                )
                continue

            updated[rel_path] = public_url
            created += 1

            _logger.info("NC sync: partage créé pour %s", rel_path)

            if delay:
                time.sleep(delay)

        stats = {
            "existing": len(folder_shares),
            "created": created,
            "missing": missing,
            "errors": errors,
            "limited": limited,
        }

        _logger.info(
            "NC sync: liens dossiers - existants=%s, créés=%s, manquants=%s, erreurs=%s, limités=%s",
            stats["existing"],
            stats["created"],
            stats["missing"],
            stats["errors"],
            stats["limited"],
        )

        return updated, stats

    def _ensure_missing_file_shares(
        self,
        remote_items: list[dict[str, Any]],
        file_shares: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, int]]:
        """
        Crée les liens publics manquants pour les fichiers uniquement.

        Important :
        - On réutilise toujours les liens existants.
        - On ne crée jamais de lien si relative_path est déjà dans file_shares.
        - On peut limiter le nombre de créations par run avec share_create_limit.
        """
        if not self._get_auto_create_file_shares():
            _logger.info("NC sync: création automatique des liens fichiers désactivée.")
            return dict(file_shares), {
                "existing": len(file_shares),
                "created": 0,
                "missing": 0,
                "errors": 0,
                "limited": 0,
            }

        root_path = self._get_root_path().rstrip("/")
        delay = self._get_share_create_delay_seconds()
        limit = self._get_share_create_limit()

        updated = dict(file_shares)

        file_items = [
            item for item in remote_items
            if item.get("type") == "file" and item.get("relative_path")
        ]

        created = 0
        missing = 0
        errors = 0
        limited = 0

        for item in file_items:
            rel_path = item["relative_path"]

            if rel_path in updated:
                continue

            if limit and created >= limit:
                limited += 1
                continue

            missing += 1
            nc_path = f"{root_path}/{rel_path}".replace("//", "/")

            try:
                public_url = self._create_public_share(nc_path)

            except RuntimeError as e:
                if str(e) == "NEXTCLOUD_RATE_LIMIT":
                    errors += 1
                    safe_delay = max(delay, 30)

                    _logger.warning(
                        "NC sync: rate limit Nextcloud détecté pour %s. Pause %ss puis arrêt du batch.",
                        rel_path,
                        safe_delay,
                    )

                    time.sleep(safe_delay)
                    break

                raise

            except Exception as e:
                errors += 1
                _logger.warning(
                    "NC sync: impossible de créer le partage pour %s: %s",
                    rel_path,
                    e,
                )
                continue

            updated[rel_path] = public_url
            created += 1

            _logger.info("NC sync: partage créé pour %s", rel_path)

            if delay:
                time.sleep(delay)
        

        stats = {
            "existing": len(file_shares),
            "created": created,
            "missing": missing,
            "errors": errors,
            "limited": limited,
        }

        _logger.info(
            "NC sync: liens fichiers - existants=%s, créés=%s, manquants=%s, erreurs=%s, limités=%s",
            stats["existing"],
            stats["created"],
            stats["missing"],
            stats["errors"],
            stats["limited"],
        )

        return updated, stats

    def _build_tree_from_flat(
        self,
        items: list[dict[str, Any]],
        folder_shares: dict[str, str],
        file_shares: dict[str, str],
        previous_files_by_key: dict[str, dict[str, Any]] | None = None,
        now_iso: str | None = None,
    ) -> dict[str, Any]:
        previous_files_by_key = previous_files_by_key or {}
        now_iso = now_iso or datetime.now(timezone.utc).isoformat()

        directories = {
            item["relative_path"]: dict(item)
            for item in items
            if item["type"] == "directory"
        }
        files = [dict(item) for item in items if item["type"] == "file"]

        # Racine de secours
        if "" not in directories:
            directories[""] = {
                "type": "directory",
                "name": PurePosixPath(self._get_root_path()).name or "Centre de ressources",
                "relative_path": "",
                "parent_relative_path": "",
                "size_bytes": 0,
                "mime_type": None,
                "modified_at": None,
                "file_id": None,
                "children": [],
            }

        for directory in directories.values():
            rel = directory["relative_path"]
            category = self._category_from_rel_path(rel)
            directory["category"] = category
            directory["category_url"] = folder_shares.get(category or "", None)
            directory["share_url"] = folder_shares.get(rel, None)
            directory["children"] = []

        for file_item in files:
            rel = file_item["relative_path"]
            category = self._category_from_rel_path(rel)
            extension = os.path.splitext(file_item["name"])[1].lower()

            previous_item = previous_files_by_key.get(rel)

            if previous_item:
                file_item["first_seen_at"] = previous_item.get("first_seen_at") or file_item.get("modified_at") or now_iso
            else:
                file_item["first_seen_at"] = file_item.get("modified_at") or now_iso

            file_item["category"] = category
            file_item["category_url"] = folder_shares.get(category or "", None)
            file_item["share_url"] = file_shares.get(rel, None)
            file_item["extension"] = extension
            file_item["size_human"] = self._human_size(file_item["size_bytes"])
            file_item["created_at"] = file_item.get("created_at")
            file_item["page_count"] = file_item.get("page_count")

        # Construction de l'arborescence des dossiers
        for directory in directories.values():
            if directory["relative_path"] == "":
                continue

            parent_rel = directory["parent_relative_path"]
            parent = directories.get(parent_rel)
            if parent:
                parent["children"].append(directory)
            else:
                _logger.warning(
                    "NC sync: dossier parent '%s' introuvable pour '%s', rattaché à la racine.",
                    parent_rel,
                    directory["relative_path"],
                )
                directories[""]["children"].append(directory)

        # Rattachement des fichiers
        for file_item in files:
            parent_rel = file_item["parent_relative_path"]
            parent = directories.get(parent_rel)
            if parent:
                parent["children"].append(file_item)
            else:
                _logger.warning(
                    "NC sync: dossier parent '%s' introuvable pour le fichier '%s', rattaché à la racine.",
                    parent_rel,
                    file_item["relative_path"],
                )
                directories[""]["children"].append(file_item)

        def sort_node(node: dict[str, Any]):
            children = node.get("children", [])

            dirs = sorted(
                [child for child in children if child["type"] == "directory"],
                key=lambda x: (x.get("name") or "").lower(),
            )

            file_nodes = sorted(
                [child for child in children if child["type"] == "file"],
                key=lambda x: (x.get("name") or "").lower(),
            )

            node["children"] = dirs + file_nodes

            for child in dirs:
                sort_node(child)

        tree = directories[""]
        sort_node(tree)
        return tree

    def _flatten_search_index(self, tree: dict[str, Any]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        def walk(node: dict[str, Any]):
            if node.get("type") == "file":
                item = {
                    "name": node.get("name"),
                    "relative_path": node.get("relative_path"),
                    "parent_relative_path": node.get("parent_relative_path"),
                    "category": node.get("category"),
                    "category_url": node.get("category_url"),
                    "share_url": node.get("share_url"),
                    "extension": node.get("extension"),
                    "mime_type": node.get("mime_type"),
                    "size_bytes": node.get("size_bytes"),
                    "size_human": node.get("size_human"),
                    "modified_at": node.get("modified_at"),
                    "created_at": node.get("created_at"),
                    "first_seen_at": node.get("first_seen_at"),
                    "page_count": node.get("page_count"),
                }
                item["search_text"] = self._build_search_text(item)
                results.append(item)
                return

            for child in node.get("children", []):
                walk(child)

        walk(tree)
        return results

    def _count_stats(self, search_index: list[dict[str, Any]]) -> dict[str, Any]:
        by_category = defaultdict(int)
        by_category_path = defaultdict(int)
        by_extension = defaultdict(int)

        for item in search_index:
            relative_path = item.get("relative_path") or ""
            parts = PurePosixPath(relative_path).parts

            category_path = parts[0] if parts else "__root__"
            category_label = item.get("category") or category_path or "Sans catégorie"

            by_category[category_label] += 1
            by_category_path[category_path] += 1
            by_extension[item.get("extension") or "Sans extension"] += 1

        return {
            "total_files": len(search_index),
            "by_category": dict(sorted(by_category.items(), key=lambda kv: kv[0].lower())),
            "by_category_path": dict(sorted(by_category_path.items(), key=lambda kv: kv[0].lower())),
            "by_extension": dict(sorted(by_extension.items(), key=lambda kv: kv[0].lower())),
        }

    def _simplify_tree_for_public(self, node: dict[str, Any]) -> dict[str, Any]:
        children = node.get("children", [])
        directory_children = [child for child in children if child.get("type") == "directory"]
        file_count = sum(1 for child in children if child.get("type") == "file")

        result = {
            "name": node.get("name", ""),
            "type": "directory",
            "file_count": file_count,
        }
        if directory_children:
            result["children"] = [self._simplify_tree_for_public(child) for child in directory_children]
        return result

    # =========================
    # READ / WRITE JSON
    # =========================

    def _write_json(self, path: str, payload: dict[str, Any]):
        directory = os.path.dirname(path)

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = tmp.name

        os.replace(tmp_path, path)

    def _read_json(self, path: str, fallback: dict[str, Any]) -> dict[str, Any]:
        if not os.path.exists(path):
            return fallback
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_private_payload(self) -> dict[str, Any]:
        return self._read_json(
            self._get_private_json_path(),
            {
                "generated_at": None,
                "stats": {"total_files": 0, "by_category": {}, "by_extension": {}},
                "tree": None,
                "search_index": [],
            },
        )


    # =========================
    # MAIN SYNC
    # =========================

    @api.model
    def run_daily_sync(self):
        self.sudo().sync_nextcloud_index()

    @api.model
    def sync_nextcloud_index(self):
        base_url = self._get_base_url()
        username = self._get_username()
        password = self._get_password()

        if not base_url or not username or not password:
            _logger.warning("Sync Nextcloud ignorée: configuration incomplète.")
            return False

        _logger.info("Début synchronisation Nextcloud pour le centre de ressources")

        folder_shares, file_shares = self._fetch_public_shares()
        remote_items = self._scan_remote_tree()

        folder_shares, folder_share_creation_stats = self._ensure_missing_folder_shares(
            remote_items,
            folder_shares,
        )

        file_shares, file_share_creation_stats = self._ensure_missing_file_shares(
            remote_items,
            file_shares,
        )

        share_creation_stats = {
            "folders": folder_share_creation_stats,
            "files": file_share_creation_stats,
        }

        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        previous_files_by_key = {}

        try:
            previous_payload = self._read_json(
                self._get_private_json_path(),
                {"search_index": []},
            )
            previous_index = previous_payload.get("search_index", [])

            previous_files_by_key = {
                item.get("relative_path"): item
                for item in previous_index
                if item.get("relative_path")
            }

        except Exception as e:
            _logger.info(
                "Aucun index précédent exploitable trouvé (première synchro ?): %s",
                e,
            )

        tree = self._build_tree_from_flat(
            remote_items,
            folder_shares,
            file_shares,
            previous_files_by_key=previous_files_by_key,
            now_iso=now_iso,
        )
        self._upsert_folders_from_tree(tree)

        search_index = self._flatten_search_index(tree)
        stats = self._count_stats(search_index)

        private_payload = {
            "generated_at": now_iso,
            "scan_root": self._get_root_path(),
            "folder_share_links": folder_shares,
            "file_share_links": file_shares,
            "share_creation_stats": share_creation_stats,
            "stats": stats,
            "tree": tree,
            "search_index": search_index,
        }

        self._write_json(self._get_private_json_path(), private_payload)

        _logger.info("Synchronisation terminée. %s fichiers indexés.", stats["total_files"])
        return True