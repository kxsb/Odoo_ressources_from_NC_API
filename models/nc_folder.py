from odoo import fields, models


class RessourcesNcFolder(models.Model):
    _name = "ressources.nc.folder"
    _description = "Dossier du centre de ressources"
    _order = "relative_path asc"

    name = fields.Char(string="Nom", required=True)
    relative_path = fields.Char(string="Chemin relatif", required=True, index=True)
    parent_path = fields.Char(string="Chemin parent", index=True)

    file_count = fields.Integer(string="Nombre de fichiers", default=0)

    visibility = fields.Selection(
        [
            ("public", "Tout public"),
            ("network", "Utilisateur connecté"),
            ("members", "Membre ou accrédités"),
            ("internal", "Utilisateurs internes"),
        ],
        string="Visibilité",
        default="network",
        required=True,
    )

    active = fields.Boolean(string="Actif", default=True)

    _sql_constraints = [
        (
            "relative_path_unique",
            "unique(relative_path)",
            "Un dossier existe déjà pour ce chemin.",
        )
    ]