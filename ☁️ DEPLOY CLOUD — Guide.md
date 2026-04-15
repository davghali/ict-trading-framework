# ☁️ DÉPLOIEMENT CLOUD — Guide pas à pas

**Objectif** : ton site tourne **24/7** gratuitement dans le cloud, **même ton Mac éteint**.

---

## ⚡ LA COMMANDE UNIQUE (recommandé)

**Double-clique** : `☁️ Deploy Cloud 24-7.command`

Le script te guide de A à Z :
1. Demande ton username GitHub (ou t'aide à en créer un)
2. T'ouvre la page pour créer un token (copie-colle)
3. Crée le repo privé sur ton compte
4. Push ton code
5. T'ouvre Streamlit Cloud avec les paramètres pré-remplis
6. Tu cliques "Deploy" → ton site est live

**Durée totale** : 10 minutes.

---

## 📋 CE QUE TU AURAS À LA FIN

### URL permanente gratuite 24/7
```
https://ton-username-ict-framework.streamlit.app
```

### Fonctionnement
- **Gratuit pour toujours** (Streamlit Community Cloud)
- **24/7** — pas de sleep (contrairement à Render free)
- **Auto-update** : à chaque `git push`, le site se met à jour
- **Repo privé** : personne ne voit ton code
- **Site public** : n'importe qui avec l'URL accède

### Ce qui marche sur le cloud
- ✓ Les 7 pages du dashboard
- ✓ Scanner de signaux (télécharge la data tout seul)
- ✓ Analyse du jour
- ✓ Espérances (chiffres)
- ✓ News calendar
- ✓ Settings persistants (pour ton navigateur)

### Ce qui ne marche PAS sur le cloud
- ✗ Notifications desktop macOS (normal, pas de Mac)
- ✗ Auto-start LaunchAgents (normal)
- ✗ Le daemon scanner de fond (à compenser par alertes Discord/Telegram)

---

## 🔐 IMPORTANT — SÉCURITÉ

Par défaut, **n'importe qui avec l'URL peut accéder à ton site**.

Avant de le partager, **demande-moi** : "ajoute un password sur le cloud" → je te fais ça en 30 secondes.

---

## ❓ FAQ

**Q: Ça me coûte quoi ?**
R: 0€. Streamlit Community Cloud est gratuit forever pour usage personnel.

**Q: Et si je veux MON domaine `ict-quant.fr` ?**
R: Achète le domaine sur OVH (10€/an), puis on migre sur Render.com qui supporte les domaines custom gratuits.

**Q: Comment je mets à jour le code ?**
R: Tu modifies les fichiers localement, puis :
```bash
cd "/Users/davidghali/DAVID DAVID/ict-institutional-framework"
git add .
git commit -m "Update"
git push
```
Streamlit Cloud rebuild automatiquement en 1-2 min.

**Q: Le site va-t-il avoir la même URL publique que maintenant ?**
R: Non, la nouvelle URL sera `https://*.streamlit.app` (permanente).
L'URL cloudflared (`*.trycloudflare.com`) disparaît — tu n'en as plus besoin.

**Q: Je peux garder le cloudflared en plus pour backup ?**
R: Oui, les 2 peuvent coexister. Mais inutile — le cloud est meilleur à tout point.

---

## 🚀 PROCHAINE ÉTAPE

**Double-clique maintenant** : `☁️ Deploy Cloud 24-7.command`

Dis-moi si tu bloques sur une étape — je te débloque en direct. 🔥
