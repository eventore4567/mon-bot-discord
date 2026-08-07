"""Catalogue étendu des rôles de notifications du panneau SentriX."""

from . import rolepanel_notifications


EXTENDED_NOTIFICATION_ROLES = (
    ("Notifications annonces", "Recevoir les annonces importantes du serveur."),
    ("Notifications événements", "Être prévenu lors des événements du serveur."),
    ("Notifications animations", "Être prévenu lors des animations communautaires."),
    ("Notifications giveaways", "Être prévenu lors des giveaways."),
    ("Notifications concours", "Être prévenu lors des concours spéciaux."),
    ("Notifications mises à jour", "Recevoir les mises à jour importantes du serveur."),
    ("Notifications nouveautés", "Recevoir les nouveautés générales du serveur."),
    ("Notifications sondages", "Être prévenu lorsqu'un nouveau sondage est publié."),
    ("Notifications recrutements", "Être prévenu lors des ouvertures de recrutements."),
    ("Notifications partenariats", "Recevoir les annonces de partenariats."),
    ("Notifications boutique", "Être prévenu des nouveautés de la boutique."),
    ("Notifications promotions", "Recevoir les promotions et offres temporaires."),
    ("Notifications tournois", "Être prévenu lors des tournois et compétitions."),
    ("Notifications mini-jeux", "Être prévenu des sessions de mini-jeux."),
    ("Notifications gaming", "Recevoir les annonces liées aux jeux et sessions gaming."),
    ("Notifications YouTube", "Être prévenu lors d'une nouvelle vidéo YouTube."),
    ("Notifications YouTube Shorts", "Être prévenu lors d'un nouveau Short YouTube."),
    ("Notifications TikTok", "Être prévenu lors d'une nouvelle publication TikTok."),
    ("Notifications Twitch", "Être prévenu lors des lives et annonces Twitch."),
    ("Notifications lives", "Être prévenu lorsqu'un live commence."),
    ("Notifications streams", "Recevoir les annonces de streams du serveur."),
    ("Notifications maintenance", "Être prévenu des maintenances et interruptions."),
    ("Notifications règlement", "Être prévenu lorsqu'une règle importante change."),
    ("Notifications SentriX", "Recevoir les nouveautés et mises à jour du bot SentriX."),
    ("Notifications communauté", "Recevoir les annonces importantes de la communauté."),
)


def install() -> None:
    """Remplace uniquement le catalogue, sans modifier la logique du panneau."""
    rolepanel_notifications.DEFAULT_NOTIFICATION_ROLES = EXTENDED_NOTIFICATION_ROLES
