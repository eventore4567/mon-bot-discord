# SentriX Premium : préparation uniquement

L'utilitaire utils/premium.py vérifie en lecture seule les abonnements **serveur**
officiels Discord, avec un cache de 5 minutes. Aucun module n'est verrouillé,
aucun SKU n'est créé, aucune vente n'est activée.

## Pré-requis avant lancement

- Application Discord vérifiée et rattachée à une équipe développeur éligible.
- Responsable d'équipe âgé de 18 ans ou plus et situé dans une zone prise en
  charge par Discord, avec vérifications et données de paiement conformes.
- Créer un SKU officiel de type **Guild Subscription** dans le Developer Portal.
- Une fois créé, définir SENTRIX_PREMIUM_SKU_ID dans la configuration.
- Décider et tester avec le propriétaire de SentriX les fonctionnalités payantes ;
  conserver un bot gratuit réellement utile (modération, sécurité, tickets, logs).
- Ajouter ensuite seulement des vérifications de droits et une page d'offre
  honnête, lisible et conforme aux règles Discord.
- Pour l'instant, aucun bouton d'achat et aucun faux badge Premium.

Sources : https://support-dev.discord.com/hc/en-us/articles/17709085688727
et https://support-dev.discord.com/hc/en-us/articles/17708927296663 .
