import copy
import json

from odoo import http
from odoo.http import request


class ressourceCenterController(http.Controller):

    # -------------------------
    # Helpers
    # -------------------------

    def _json_response(self, payload):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json; charset=utf-8")],
        )

    def _get_user_level(self):
        user = request.env.user

        if user._is_public():
            return "public"

        if user.has_group("base.group_user"):
            return "internal"

        return "network"

    def _allowed_visibilities(self, user_level):
        if user_level == "public":
            return {"public"}

        if user_level == "network":
            # V1 : members est volontairement traité comme network.
            return {"public", "network", "members"}

        if user_level == "internal":
            return {"public", "network", "members", "internal"}

        return {"public"}

    def _get_visibility_map(self):
        folders = request.env["ressources.nc.folder"].sudo().search([])

        return {
            folder.relative_path or "": folder.visibility
            for folder in folders
            if folder.active
        }

    def _get_path_visibility(self, path, visibility_map):
        if not path:
            return visibility_map.get("", "network")

        # 🔥 tri du plus spécifique au moins spécifique
        sorted_paths = sorted(
            visibility_map.keys(),
            key=lambda p: len(p or ""),
            reverse=True,
        )

        for prefix in sorted_paths:
            if not prefix:
                continue
            if path.startswith(prefix):
                return visibility_map[prefix]

        return visibility_map.get("", "network")

    def _is_path_allowed(self, path, visibility_map, allowed):
        visibility = self._get_path_visibility(path, visibility_map)
        return visibility in allowed

    def _decorate_tree(self, node, visibility_map, allowed):
        if not node:
            return None

        decorated = copy.deepcopy(node)
        node_type = decorated.get("type")

        if node_type == "directory":
            path = decorated.get("relative_path") or ""
            visibility = self._get_path_visibility(path, visibility_map)
            locked = visibility not in allowed if path else False

            decorated["visibility"] = visibility
            decorated["locked"] = locked
            decorated["required_visibility"] = visibility
            decorated["required_visibility_label"] = self._visibility_label(visibility)

            # 🔒 Sécurité : ne jamais exposer un lien de dossier Nextcloud.
            # Un partage dossier peut donner accès à tout un sous-arbre.
            decorated["share_url"] = None
            decorated["category_url"] = None

            decorated["children"] = [
                self._decorate_tree(child, visibility_map, allowed)
                for child in decorated.get("children", [])
            ]

            return decorated

        if node_type == "file":
            parent_path = decorated.get("parent_relative_path") or ""
            visibility = self._get_path_visibility(parent_path, visibility_map)
            locked = visibility not in allowed

            decorated["visibility"] = visibility
            decorated["locked"] = locked
            decorated["required_visibility"] = visibility
            decorated["required_visibility_label"] = self._visibility_label(visibility)

            # 🔒 Pas de fallback dossier/category côté frontend.
            decorated["category_url"] = None

            if locked:
                decorated["share_url"] = None

            return decorated

        return decorated

    def _visibility_label(self, visibility):
        return {
            "public": "Tout public",
            "network": "Utilisateur connecté",
            "members": "Membres ou accrédités",
            "internal": "Utilisateurs internes",
        }.get(visibility, "Compte public")

    def _decorate_search_index(self, search_index, visibility_map, allowed):
        decorated_items = []

        for item in search_index:
            decorated = copy.deepcopy(item)
            parent_path = decorated.get("parent_relative_path") or ""
            visibility = self._get_path_visibility(parent_path, visibility_map)
            locked = visibility not in allowed

            decorated["visibility"] = visibility
            decorated["locked"] = locked
            decorated["required_visibility"] = visibility
            decorated["required_visibility_label"] = self._visibility_label(visibility)

            if locked:
                decorated["share_url"] = None
                decorated["category_url"] = None

            decorated_items.append(decorated)

        return decorated_items

    def _filter_search_index(self, search_index, visibility_map, allowed):
        return [
            item
            for item in search_index
            if self._is_path_allowed(
                item.get("parent_relative_path") or "",
                visibility_map,
                allowed,
            )
        ]

    def _filter_payload_for_current_user(self, payload):
        user_level = self._get_user_level()
        allowed = self._allowed_visibilities(user_level)
        visibility_map = self._get_visibility_map()

        decorated_tree = self._decorate_tree(
            payload.get("tree"),
            visibility_map,
            allowed,
        )

        allowed_search_index = self._filter_search_index(
            payload.get("search_index", []),
            visibility_map,
            allowed,
        )

        return {
            "generated_at": payload.get("generated_at"),
            "scan_root": payload.get("scan_root"),
            "stats": payload.get("stats", {}),
            "share_creation_stats": payload.get("share_creation_stats", {}),
            "tree": decorated_tree,
            "search_index": self._decorate_search_index(
                allowed_search_index,
                visibility_map,
                allowed,
            ),
            "access_level": user_level,
            "allowed_visibilities": sorted(allowed),
        }

    # -------------------------
    # Routes
    # -------------------------

    @http.route("/ressource_center/data/private", type="http", auth="user", website=True)
    def ressource_center_private(self, **kwargs):
        payload = request.env["ressources.nc.sync"].sudo().get_private_payload()
        payload = self._filter_payload_for_current_user(payload)
        return self._json_response(payload)

    @http.route("/ressource_center/data/public", type="http", auth="public", website=True)
    def ressource_center_public(self, **kwargs):
        payload = request.env["ressources.nc.sync"].sudo().get_private_payload()

        visibility_map = self._get_visibility_map()
        allowed = {"public"}

        # 🔒 filtrage strict
        filtered_search_index = self._filter_search_index(
            payload.get("search_index", []),
            visibility_map,
            allowed,
        )

        filtered_tree = self._decorate_tree(
            payload.get("tree"),
            visibility_map,
            allowed,
        )

        filtered = {
            "generated_at": payload.get("generated_at"),
            "scan_root": payload.get("scan_root"),
            "stats": payload.get("stats", {}),
            "tree": filtered_tree,
            "search_index": self._decorate_search_index(
                filtered_search_index,
                visibility_map,
                allowed,
            ),
            "access_level": "public",
            "allowed_visibilities": ["public"],
        }

        return self._json_response(filtered)
