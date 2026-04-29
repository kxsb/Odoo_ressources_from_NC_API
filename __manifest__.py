{
    "name": "Ressources from NC API",
    "version": "18.0.1.0.0",
    "summary": "Centre de ressources synchronisé depuis Nextcloud",
    "author": "Mouvement Sol",
    "category": "Website",
    "depends": ["website"],
    "data": [
        "data/ir_cron.xml",
        "security/ressource_center_groups.xml",
        "security/ir.model.access.csv",
        "views/nc_folder_views.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "ressources_from_NC_API/static/src/js/ressource_center.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}