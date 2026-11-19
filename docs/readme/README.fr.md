# HaoYuan · 豪源

[简体中文](../../README.md) · [繁體中文](README.zh-TW.md) · [English](README.en.md) · [日本語](README.ja.md) · [Deutsch](README.de.md) · [한국어](README.ko.md)  
**Français** · [Español](README.es.md) · [Português (Brasil)](README.pt-BR.md) · [Italiano](README.it.md) · [Polski](README.pl.md) · [Toutes les langues](README.md)

> Un studio d’IA personnel où vous dirigez plusieurs employés IA pour travailler en parallèle de manière asynchrone.  
> Un noyau, un ensemble de plugins installables et une boucle fermée vérifiable pour des tâches à long horizon.

HaoYuan est réécrit au-dessus de **agent-harness** comme fondation de référence pour son backend. Il préserve et renforce l’expertise de codage d’un assistant IA tout en réorganisant les sessions, les outils, les agents, le routage, les compétences, la supervision et l’orchestration autour d’une architecture de plugins. Le frontend est entièrement réécrit, avec pour objectif de faire évoluer « la collaboration IA » d’une fenêtre de chat vers un banc de travail que vous pouvez diriger, observer et dans lequel vous pouvez intervenir.

![Banc de travail](../screenshots/workbench-dark.png)

---

## 1. Fonctionnalités principales

### 1.1 Une boucle de codage réellement utilisable

| Capacité | Implémentation |
|---|---|
| Perception du dépôt | `project_scan`, `repo_map`, index de symboles, `search_symbol` |
| Lecture précise | `read_file`, `read_range`, ciblage par numéro de ligne |
| Modifications minimales | `apply_patch` (diff unifié / SEARCH-REPLACE), `edit_file`, `multi_edit` |
| Opérations sur les fichiers | `write_file`, `glob`, `grep`, `list_dir`, `delete_path`, `move_path` |
| Vérification des commandes | `run_shell` (UTF-8, délais d’expiration, résumés d’erreurs structurés), `git` (wrapper) |
| Porte de vérification | Les tests/lint/build sont obligatoires après toute modification de code, ce qui empêche de « modifier sans vérifier » |
| Boucle test-correction | Analyse structurée des échecs pytest → localisation de ligne → correction minimale → escalade par empreinte d’échec |
| Sous-agents | `task` explore dans un contexte isolé et ne renvoie que des conclusions, évitant ainsi la pollution du contexte principal |
| Gouvernance du contexte | Vieillissement des résultats d’outils, résumés structurés, compression en cours de tour, élagage sous budget strict |
| Préchargement du contexte | Classement `repo_map` tenant compte des exigences, plus un `context_pack` de sources pertinentes pour les tâches complexes (jusqu’à ~30 Ko), ce qui réduit les lectures complètes répétées |
| Tâches à long horizon | Budgets d’étapes, poursuite automatique, points de contrôle, registre idempotent des effets de bord (les écritures ne sont pas réappliquées) |
| Humain dans la boucle | Les écritures/commandes à haut risque affichent un aperçu du diff et ne s’exécutent qu’après approbation |

Hiérarchisation des intentions de session : les salutations, les conversations légères et les questions-réponses générales reçoivent une réponse directe sans analyser l’espace de travail, sans déclencher d’outils et sans écrire ; seules les tâches explicites telles que le codage, les modifications de fichiers et l’exécution de commandes entrent dans la boucle de codage.

### 1.2 Parallélisme asynchrone multi-session

- Une session = un `asyncio.Task` en arrière-plan ; changer de fenêtre, fermer des onglets ou se déconnecter n’arrête pas la tâche.
- Porte de concurrence globale + file FIFO ; en attente d’une approbation humaine, le créneau de concurrence est libéré automatiquement.
- Machine à états de session : `idle → queued → running ⇄ waiting_input → done / error`.
- Barre d’onglets de session en haut de l’espace de travail : créer ou ouvrir une session ajoute automatiquement un onglet ; un clic permet de basculer horizontalement ; `×` ferme uniquement la vue sans supprimer la session, et les onglets persistent après actualisation ; un clic droit sur un onglet permet de fermer la conversation courante / celles à gauche / à droite / toutes.
- Le premier message d’une nouvelle session reçoit du modèle un titre court dans la langue actuelle de l’interface ; si une ancienne session a encore le titre par défaut, un résumé est affiché automatiquement à partir du premier message.
- Chaque session possède sa propre URL `/#/s/<session-id>`, qui peut être copiée, actualisée, partagée, ou utilisée pour basculer directement depuis la barre d’adresse.
- Après actualisation de la page, les messages, événements, plans, approbations et artefacts sont restaurés depuis SQLite.
- Le canal principal d’événements en temps réel utilise SSE (reconnexion, reprise basée sur un curseur, streaming même sans WebSocket) ; le point de terminaison WebSocket reste disponible pour compatibilité ; REST prend en charge la relecture des événements.

### 1.3 Superviseur IA et orchestration multi-agents

- **Superviseur** : contrôles de santé inter-sessions, alertes sur les tâches bloquées, interruption automatique, conversations de console et actions de planification.
- **Orchestrateur** : objectif → DAG de tâches → un git worktree indépendant par employé → exécution parallèle → fusion et acceptation.
- Les sessions des employés partagent des fichiers de contrat et un tableau noir commun ; une défaillance ne bloque pas les autres tâches de la même couche.

### 1.4 Bibliothèque de compétences

- Markdown + front-matter déclarant `name / title / description / kinds / triggers`.
- Mise en correspondance automatique selon le type de tâche et les mots-clés ; le classement BM25 s’active lorsqu’il y a de nombreuses compétences.
- Intégrées : méthodologie cœur, boucle d’ingénierie du dépôt, boucle de débogage, livraison web et rédaction de propositions.
- Les compétences peuvent être créées, modifiées et supprimées dans l’interface ; les modifications prennent effet à l’enregistrement.

### 1.5 Documents de plan

- `make_plan` : génère une proposition/un plan HTML autonome avec KPI, sections, tableaux, risques et jalons.
- Les artefacts sont enregistrés sous `api/data/artifacts/` et peuvent être prévisualisés/téléchargés directement depuis la partie droite de l’espace de travail.

### 1.6 Architecture de plugins

HaoYuan n’est pas « un seul monolithe géant » ; il s’agit de :

```
Kernel (sessions / events / tool registry / policy / model gateway / approvals)
        │
        ├── coding       coding agent + engineering tools + skills
        ├── plans        planning tools + Planner agent
        ├── supervisor   health checks + console routes
        ├── orchestrator task DAG + worktree + merge
        └── embodied     embodied agent harness (disabled by default, install to enable)
```

Les plugins peuvent fournir : des outils, des agents, des routes HTTP, des répertoires de compétences, des abonnements à des événements, des hooks de cycle de vie et des métadonnées de navigation/commande côté frontend. L’échec de chargement d’un seul plugin ne fait pas tomber le noyau.

![Plugins](../screenshots/plugins.png)

### 1.7 Onze langues, mode clair par défaut et barre latérale repliable

- Thème **clair (blanc)** par défaut ; basculez vers le thème sombre depuis la page des paramètres ou depuis le bas de la barre latérale.
- **Chinois simplifié** par défaut ; basculez entre **简体中文 / 繁體中文 / English / 日本語 / Deutsch / 한국어 / Français / Español / Português (Brasil) / Italiano / Polski**.
- Les points d'accès à la langue se trouvent à trois endroits bien visibles : la barre supérieure du plan de travail, le bas de la barre latérale (disponible sur toutes les pages) et Paramètres → Apparence.
- Le choix est conservé dans `localStorage` et survit au rafraîchissement comme au redémarrage ; `document.lang` et le titre de la page sont également mis à jour.
- La barre latérale peut être réduite en un rail d'icônes de 76 px ; une fois réduite, un bouton explicite « Développer la barre latérale » reste affiché en haut, la liste des sessions est masquée, et tout est restauré à l'extension.
- Le panneau d'informations de droite est réduit par défaut afin de laisser plus de place à la conversation ; cliquez sur le bouton en haut à droite pour l'ouvrir, et le choix est conservé.
- Les titres/descriptions des compétences intégrées, les titres/descriptions des plugins et les textes d'interface pour les statuts, boutons, astuces, approbations, plans, utilisation et orchestration sont entièrement couverts dans les onze langues.

---

## 2. Démarrage rapide

### Statistiques d'utilisation anonymes (avis de transparence)

HaoYuan inclut un signal d'utilisation (heartbeat) **entièrement anonyme** permettant de compter les appareils en ligne et la répartition des versions :

- **Données transmises** : un `install_id` (UUID) aléatoire généré localement, la version du client et le type de système d'exploitation (par ex. `Windows 11`). Il ne contient aucun nom d'utilisateur, adresse e-mail, contenu de fichier, chemin d'espace de travail, contenu de conversation ni aucune autre donnée personnelle.
- **Fréquence** : une fois au démarrage et toutes les 5 minutes pendant l'exécution (une seule requête POST légère).
- **Entièrement facultatif** : définissez la variable d'environnement `HAOYUAN_TELEMETRY=0` avant le démarrage pour le désactiver définitivement ; toutes les fonctionnalités restent inchangées.
- **Protection de la vie privée** : le serveur n'enregistre qu'un hachage à sens unique de l'IP, jamais l'IP en clair ; les données sont conservées pendant 90 jours.
- **Avis complet** : voir le point de terminaison de confidentialité du centre de plugins `GET {plugin-center-url}/api/plugin-center/privacy`, ou le code source `api/core/telemetry.py` (~100 lignes, auditable).

### Prérequis

- Python 3.10+
- Node.js 18+
- Windows / Linux / macOS

### Installation via npm (recommandé)

```bash
# Prerequisite: Node.js 18+ and Python 3.10+
npm install -g haoyuan

# Faster mirrors in mainland China:
npm install -g haoyuan --registry=https://registry.npmmirror.com

# Terminal chat (creates the venv and installs dependencies on first run)
haoyuan

# Start the service and open the web UI automatically
haoyuan web
```

| Commande | Objectif |
|---|---|
| `haoyuan` | Chat dans le terminal (sortie en streaming, appels d'outils, invites d'approbation) |
| `haoyuan --model x/y` | Démarrer le chat avec un modèle spécifique (par ex. `--model deepseek/deepseek-flash`) |
| `haoyuan web` | Démarrer le service et ouvrir automatiquement l'interface web |
| `haoyuan web --no-open` | Démarrer le service sans ouvrir de navigateur |
| `haoyuan --version` / `-V` | Afficher la version |
| `haoyuan config` | Fichier de configuration global (clés de modèle, etc.) ; utilisez `--open` pour le modifier directement |
| `haoyuan login` / `haoyuan logout` | Se connecter lorsque la protection de compte est activée / effacer le jeton local |
| `haoyuan setup` | Installer uniquement les dépendances |
| `haoyuan help` | Afficher l'aide |

Commandes dans le terminal : `/models` pour afficher/sélectionner un modèle (choisir par numéro, ou `/model x/y` pour sélectionner directement), `/new` pour créer une session, `/web` pour ouvrir la session actuelle dans un navigateur, `/cancel` pour annuler la tâche en cours, `/exit` pour quitter (Ctrl+C fonctionne aussi).

L'interface web utilise par défaut `http://127.0.0.1:8030` et incrémente automatiquement le port lorsqu'il est utilisé. Sans clé de modèle, le modèle `mock` intégré exécute toujours les sessions, les appels d'outils, les approbations et le frontend de bout en bout.

### Démarrage en un clic sous Windows

```bat
start.bat
```

Le script effectue automatiquement les opérations suivantes : arrête l'ancien processus sur le port 8030 → crée `api/env1` → installe les dépendances Python → (uniquement lorsque `web/dist` est absent) installe les dépendances frontend et compile → démarre l'API et ouvre la page du produit. Le paquet npm fournit déjà un frontend précompilé, de sorte que les environnements intranet/hors ligne peuvent démarrer directement une fois les dépendances installées. Si un précédent `npm install` a laissé un `web/node_modules` incomplet en raison d'une interruption réseau, le script le détecte et le réinstalle automatiquement — aucune suppression manuelle n'est nécessaire.

**Repli automatique des ports** : le backend utilise par défaut `8030` et le serveur de développement frontend `8130` ; si un port est utilisé, il s'incrémente automatiquement (8031, 8032, …) jusqu'à ce que la liaison réussisse. Les ports réels sont écrits dans `api/data/runtime.json`, et le script de démarrage les lit pour ouvrir l'adresse correcte. Vous pouvez également définir explicitement les ports de base avec `HAOYUAN_PORT` / `HAOYUAN_WEB_PORT` (frontend) et `HAOYUAN_API_PORT` (cible du proxy frontend).

Arrêter :

```bat
stop.bat
```

### Console de bureau (desktop.exe)

Double-cliquez sur `desktop.exe` à la racine du dépôt pour ouvrir la console graphique (~20 Ko, dépendant uniquement de .NET Framework 4.x fourni avec Windows) :

- **Tout démarrer / tout arrêter** : gérer le backend et le serveur de développement frontend en un clic ; la page du produit s'ouvre automatiquement après le démarrage
- **Démarrer / arrêter le backend** (8030 par défaut) et **démarrer / arrêter le frontend** (8130 par défaut)
- **Paramètres des ports** : modifiez directement les ports backend/frontend ; cliquez sur « Appliquer les ports et redémarrer » pour enregistrer la configuration et redémarrer les deux services ; si un port est occupé, le service s'incrémente quand même automatiquement
- **Ouvrir la page du produit** : ouvre le port réel du backend depuis `api/data/runtime.json` ; se rabat sur le port du frontend lorsque seul le frontend est en cours d'exécution
- **Compiler le frontend**, **ouvrir le dossier du projet**, état des services actualisé chaque seconde et journaux d'exécution en direct

La fermeture de la fenêtre de console n'arrête pas les services. Pour les arrêter, cliquez sur « Tout arrêter » ou sur les boutons d'arrêt correspondants. La source se trouve dans `desktop/` ; exécutez `desktop\build.bat` pour recompiler après modification.

### Linux / macOS

```bash
bash start.sh
bash stop.sh
```

Pour les environnements intranet ou avec un miroir personnalisé, spécifiez explicitement les sources de téléchargement (si elles sont omises, les sources déjà configurées dans `~/.npmrc` et `pip.conf` sont utilisées) :

```bash
export HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
export HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
bash start.sh
```

Équivalent Windows :

```bat
set HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
set HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
start.bat
```

Lorsque les dépendances frontend ou Python sont incomplètes (par exemple, une installation précédente a été interrompue par `ECONNRESET`), `start.sh` / `start.bat` / `haoyuan setup` détectent et nettoient automatiquement `web/node_modules`, réinstallent, installent les paquets backend manquants et se rabattent sur le `web/dist` existant si la compilation échoue.

`web/package-lock.json` ne code plus en dur un miroir externe ; `replace-registry-host=always` dans `web/.npmrc` garantit que les installations utilisent toujours le registre de la configuration npm actuelle, afin que le lockfile ne puisse pas détourner les installations vers un miroir externe inaccessible.

### Démarrage manuel

```bash
# Backend
cd api
python -m venv env1
env1\Scripts\activate           # Linux: source env1/bin/activate
pip install -r requirements.txt
python main.py                  # http://127.0.0.1:8030, increments automatically if in use

# Frontend dev mode (hot reload, optional)
cd web
npm install
npm run dev                     # http://localhost:8130, increments automatically if in use; /api and /ws proxy to the backend's actual port
```

En production, le backend sert directement `web/dist`, il suffit donc de visiter le port réel du backend. Les ports peuvent être surchargés au moyen de variables d’environnement : `HAOYUAN_PORT` (backend, valeur par défaut 8030), `HAOYUAN_WEB_PORT` (frontend, valeur par défaut 8130) et `HAOYUAN_API_PORT` (cible du proxy frontend, valeur par défaut issue de `api/data/runtime.json`).

### Configurer les modèles

**Fichier de configuration global (recommandé)** — un chemin fixe par utilisateur, non affecté par une réinstallation ou une mise à niveau :

```bash
haoyuan config          # creates the file on first run and prints its path
haoyuan config --open   # open it directly in your editor
```

Chemin : `~/.config/haoyuan/config.json` (sous Windows : `C:\Users\<you>\.config\haoyuan\config.json` ; remplaçable via la variable d’environnement `HAOYUAN_CONFIG`) :

Le fichier est créé automatiquement au premier démarrage (ou par le postinstall npm), et son répertoire est créé s’il n’existe pas.

```json
{
  "PROVIDER": "",
  "MODEL": "",
  "DEEPSEEK_API_KEY": "",
  "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
  "DEEPSEEK_MODEL": "deepseek-flash",
  "ZHIPU_API_KEY": "",
  "ZHIPU_BASE_URL": "https://open.bigmodel.cn/api/coding/paas/v4",
  "ZHIPU_MODEL": "glm-5.3-flash",
  "MIMO_API_KEY": "",
  "MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
  "MIMO_MODEL": "mimo-v2.6-flash",
  "providers": {}
}
```

- Pour les fournisseurs intégrés, vous pouvez ajouter `DEEPSEEK_MODELS` / `ZHIPU_MODELS` / `MIMO_MODELS` (séparés par des virgules) afin de personnaliser entièrement la liste des modèles ; `*_THINKING_MODELS`, `*_MAX_OUTPUT` et `*_SUPPORTS_THINKING` sont facultatifs.
- Tout fournisseur compatible OpenAI peut être ajouté à l’objet `providers`, pas seulement les trois fournisseurs intégrés :

```json
{
  "providers": {
    "my-intranet": {
      "base_url": "http://llm.intranet/v1",
      "api_key": "sk-...",
      "models": ["qwen-max", "qwen-plus"],
      "default_model": "qwen-max",
      "supports_thinking": false,
      "max_output_tokens": 8192
    }
  }
}
```

- `PROVIDER` / `MODEL` peuvent fixer le modèle par défaut (par ex. `"MODEL": "deepseek-v4-pro"` ou `"MODEL": "my-intranet/qwen-max"` ; laissez vide pour une sélection automatique en fonction des clés configurées).
- **Synchronisation bidirectionnelle entre la page de paramètres web et le fichier de configuration** : les ajouts et modifications de fournisseurs, de modèles et du modèle par défaut dans « Paramètres → Configuration des modèles » sont immédiatement répercutés dans le fichier ; si vous modifiez le fichier directement et l’enregistrez, le service le recharge à la requête suivante (aucun redémarrage nécessaire).
- « Actualiser tous les modèles » interroge le point de terminaison `/models` de chaque fournisseur avec son URL de base et sa clé, en filtrant automatiquement les modèles non conversationnels ; si certains fournisseurs échouent, les fournisseurs concernés et les raisons sont affichés, tandis que les fournisseurs dont l’opération a réussi sont tout de même enregistrés.

**Configuration intégrée au paquet (facultative)** :

```bash
copy api\configs\secrets_example.py api\configs\secrets_local.py
```

Modifiez `api/configs/secrets_local.py` avec les mêmes champs (en tant que constantes Python). Cela est destiné aux déploiements depuis les sources ; pour une installation npm globale, le fichier se trouve dans le répertoire du paquet et est supprimé lors d’une mise à niveau, donc privilégiez la configuration globale.

**Variables d’environnement** (priorité la plus élevée) :

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

Priorité : variables d’environnement > fichier de configuration global > `secrets_local.py`. Après modification du fichier de configuration global, aucun redémarrage n’est nécessaire (le service effectue un rechargement à chaud) ; le champ `key_source` du contrôle de santé `GET /api/health` indique l’origine de la clé.

**Lorsqu’aucune clé n’est configurée, le modèle local `mock` est utilisé automatiquement**, ce qui permet de tester de bout en bout les sessions, les appels d’outils, les approbations, les événements et le frontend.

---

## 3. Interface

| Espace de travail (clair, par défaut) | Espace de travail (anglais) |
|---|---|
| ![](../screenshots/workbench-light.png) | ![](../screenshots/workbench-en.png) |

| Espace de travail (chinois traditionnel) | Espace de travail (sombre) |
|---|---|
| ![](../screenshots/workbench-tw.png) | ![](../screenshots/workbench-dark.png) |

| Console du superviseur | Bibliothèque de compétences |
|---|---|
| ![](../screenshots/console.png) | ![](../screenshots/skills.png) |

| Entrée des paramètres et de la langue | Bouton Développer après réduction de la barre latérale |
|---|---|
| ![](../screenshots/settings.png) | ![](../screenshots/collapsed.png) |

Panneau d’informations à droite sur mobile :  
![](../screenshots/mobile-panel.png)

Interactions clés :

- Onglets de session en haut : cliquez pour changer de conversation ; `×` ferme un onglet (les données de session ne sont pas affectées) ; clic droit pour fermer la conversation actuelle / à gauche / à droite / toutes les conversations
- Les nouvelles tâches ne proposent plus de questions prédéfinies ; décrivez simplement la tâche dans le champ de saisie et le titre de la session est résumé automatiquement
- Routage par barre d'adresse : `/#/s/<session-id>` correspond à une session spécifique et peut être copié, actualisé ou ouvert dans une nouvelle fenêtre
- `Ctrl / Cmd + K` : palette de commandes (navigation, sessions, actions)
- `Ctrl / Cmd + N` : nouvelle tâche
- `Ctrl / Cmd + B` : réduire / développer la barre latérale
- `Enter` : envoyer ; `Shift + Enter` : retour à la ligne (`Ctrl / Cmd + Enter` envoie aussi)
- Carte d'approbation : `A` approuve, `R` refuse
- Changement de langue : en haut à droite du plan de travail, en bas de la barre latérale sur n'importe quelle page, et dans Paramètres → Apparence
- Saisissez du texte pendant qu'une session est en cours : la saisie est fusionnée dans l'exécution actuelle en tant qu'« instruction supplémentaire » sans interrompre la tâche
- Le panneau de droite est réduit par défaut ; cliquez sur le bouton en haut à droite pour ouvrir Aperçu / Plan / Fichiers / Modifications / Artefacts, et faites glisser pour redimensionner
- Les fichiers et les diffs utilisent une grande superposition d'aperçu pour éviter de lire du code dans une colonne étroite

---

## 4. Architecture

```text
hao-yuan/
├── api/
│   ├── main.py                    FastAPI entry (extension routes + plugin routes + static frontend)
│   ├── configs/                   Configuration, model registry, secrets
│   ├── core/
│   │   ├── contracts.py           Tool / Agent / Policy / ToolContext
│   │   ├── storage.py             SQLite (WAL) storage layer
│   │   ├── events.py              Event bus (broadcast + batched persistence + replay)
│   │   ├── gateway.py             Model gateway (streaming + degradation + fallback)
│   │   ├── context.py             Context compression / aging / hard budget
│   │   ├── runtime.py             Agent main loop
│   │   ├── session_manager.py     Concurrency gate / queue / approvals / resume
│   │   ├── policy.py              Permission gate
│   │   ├── tools.py               Tool registry and execution
│   │   ├── agents.py              Agent registry
│   │   └── plugin.py              Plugin discovery / dependencies / lifecycle
│   ├── harness/                   Sandbox / skills / symbol index / fix loop / supervision / orchestration / embodied
│   ├── tools/                     builtin / dev / plan
│   ├── adapters/providers/        deepseek / mimo / mock
│   ├── plugins/                   coding / plans / supervisor / orchestrator / embodied
│   ├── extensions/                System / sessions / skills / settings / files / usage / plugins / approvals / real-time events (SSE / WebSocket)
│   ├── skills/                    Core skills
│   ├── tests/                     90 backend tests
│   └── data/                      Runtime data (gitignored)
├── web/                           Vue 3 + Vite
├── docs/screenshots/              UI screenshots
├── start.bat / stop.bat
├── start.sh / stop.sh
├── dev.bat
├── desktop.exe                    Graphical desktop console (start/stop services / open the web UI)
└── desktop/                       desktop.exe source and build scripts
```

### Données et limites

- Base de données : `api/data/haoyuan.db` (WAL)
- Artefacts : `api/data/artifacts/<session_id>/`
- Ports d'exécution : `api/data/runtime.json` (le backend écrit `api_port`, le frontend écrit `web_port`, et la console de bureau écrit `api_port_config` / `web_port_config`)
- Tous les outils de fichiers sont contraints par la liste d'autorisation de l'espace de travail de la session et rejettent `../` ainsi que les évasions par chemin absolu.
- Les outils à haut risque (écriture de fichiers, patch, suppression, déplacement, shell, git, mouvement du robot) nécessitent une approbation.
- `run_shell` bloque catégoriquement les commandes catastrophiques (telles que `rm -rf /`, le formatage de disque et l'arrêt de la machine).
- Le HTML des artefacts est prévisualisé via un endpoint avec une CSP sandbox, empêchant les pages générées par le modèle de lire les identifiants locaux.
- Les secrets sont lus uniquement depuis des variables d'environnement ou `secrets_local.py` ; ils ne sont jamais stockés dans la base de données ni renvoyés en clair.
- Les vraies clés résident dans `api/configs/secrets_local.py`, qui est ignoré par `.gitignore` ; `git add --dry-run` vérifie qu'elles n'entrent jamais dans le dépôt.

---

## 5. Développement de plugins

Créez un répertoire sous `api/plugins/` :

```
api/plugins/my-plugin/
├── plugin.json
├── plugin.py
├── routes.py        # optional
└── skills/          # optional
    └── my-skill.md
```

`plugin.json` :

```json
{
  "name": "my-plugin",
  "title": "My Plugin",
  "version": "1.0.0",
  "description": "What this plugin adds",
  "author": "you",
  "requires": ["coding"],
  "default_enabled": true,
  "backend": "plugin.py",
  "routes": "routes.py",
  "contributes": {
    "tools": ["my_tool"],
    "agents": ["my_agent"],
    "skills": true
  },
  "frontend": {
    "nav": [{ "label": "My Plugin", "path": "/my-plugin", "icon": "puzzle" }],
    "commands": [{ "id": "my-plugin.run", "title": "Run my plugin" }]
  }
}
```

`plugin.py` :

```python
from core.contracts import AgentSpec, ToolSpec


async def my_tool(ctx, args):
    return {"echo": args.get("text", "")}


def register(ctx):
    ctx.register_tool(
        ToolSpec(
            name="my_tool",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        my_tool,
    )
    ctx.register_agent(
        AgentSpec(
            name="my_agent",
            title="My Agent",
            instructions="You are ...",
            tools=["my_tool"],
            kind="dev",
        )
    )
    ctx.add_skill_dir("skills")


async def startup(ctx):
    ...


async def shutdown(ctx):
    ...
```

Capacités des plugins :

- `requires` contrôle l'ordre des dépendances ; les dépendances manquantes sont isolées et l'erreur est enregistrée.
- `startup / shutdown` hooks de cycle de vie.
- `ctx.events.subscribe(sink)` s'abonne aux événements globaux (c'est ainsi que l'orchestrateur reçoit les événements d'achèvement des employés).
- L'état activé/désactivé est persisté dans SQLite ; après basculement, redémarrez l'API pour charger/décharger les routes.
- Le frontend obtient les métadonnées `contributes` et `frontend` via `/api/plugins`.

### Pourquoi cette conception

Il emprunte à WordPress son modèle « noyau léger + plugins installables » : le noyau ne gère que les sessions, les événements, les politiques, les modèles et le protocole d'outils ; toutes les capacités métier résident dans des plugins.  
Il adopte également l'idée du DeepSeek Harness selon laquelle « le harness lui-même est pluggable » : un agent incarné n'est qu'un plugin de harness indépendant, de sorte que vous pouvez continuer à ajouter des harness pour des rovers, des bras robotiques, des robots humanoïdes, etc., sans toucher au noyau.

---

## 6. Résultats des autotests

Ce qui suit a été exécuté dans l'environnement de livraison :

```bash
cd api
python -m pytest -q
# 90 passed, 2 skipped, 2 warnings

cd ../web
npm run build
# ✓ built, 97 modules transformed
```

Couverture des tests :

- Vérification de l'état, modèles, compétences, plugins et liste des approbations
- Une session complète de modèle simulé (message → événement → terminé)
- Session de codage : écriture de fichier → événement d'outil → artefact → lecture de l'arborescence de l'espace de travail
- Flux d'approbation humaine : en attente → approbation → exécution de l'outil → fichier écrit sur le disque
- Renommage / masquage / restauration / effacement / suppression définitive de session
- Réglages du gate global et de l'espace de travail par défaut, utilisation et export CSV
- Persistance de l'état d'activation des plugins
- Worktree git de l'orchestrateur de bout en bout (création → répartition → achèvement → fusion)
- Niveau des outils : évasion du bac à sable, read/write/edit/patch/multi_edit, glob/grep/symbols, shell, delete/move
- Blocage strict des commandes shell dangereuses
- Index de symboles, carte du dépôt, analyse pytest et conseils de correction
- Génération d'artefacts HTML de plan
- Routage des intentions : les salutations, les bavardages et les questions-réponses générales (comme « comment vas-tu », « il fait beau aujourd'hui », « qu'est-ce que l'injection de dépendances ») reçoivent une réponse directe sans analyser l'espace de travail, déclencher des outils ni écrire (y compris une vérification réelle avec deepseek-flash)
- Titre de session automatique à partir du premier message (suit la langue de l'interface ; le mock couvre le repli et la vérification avec un modèle réel)
- Routage indépendant des sessions : liens profonds `/#/s/<session-id>`, changement d'onglet, édition de la barre d'adresse, restauration après actualisation et repli à la fermeture
- Clic droit sur l'onglet de session : fermer l'onglet courant / à gauche / à droite / tous, avec bascule automatique vers l'onglet le plus proche après une fermeture groupée
- Actualisation des modèles du fournisseur : détails des échecs et filtrage des modèles non conversationnels

En outre, une inspection en navigateur réel de la version de production a été réalisée avec Playwright + Chrome local :

- Toutes les pages Workbench / console / skills / plugins / settings / usage / orchestration se chargent
- Onglets de session supérieurs et routage indépendant : ouverture, bascule, fermeture, fermeture groupée par clic droit, liens profonds de la barre d’adresse et restauration après actualisation
- Résumé du titre par défaut, menu de langue en haut à droite (bascule entre onze langues) et état vide sans questions prédéfinies
- La commutation entre le chinois simplifié, le chinois traditionnel, l’anglais, le japonais, l’allemand, le coréen, le français, l’espagnol, le portugais brésilien, l’italien et le polonais fonctionne, et la langue est conservée après actualisation
- Les points d’entrée de langue couvrent la barre supérieure du Workbench, le bas de la barre latérale et la page de paramètres
- Le repliement/déploiement de la barre latérale entre 286px et 76px fonctionne ; après repliement, la liste des sessions est masquée et le bouton de déploiement est visible
- Le panneau d’informations à droite est replié par défaut, et son état replié/déplié est conservé
- `Enter` soumet et `Shift + Enter` insère un saut de ligne ; la composition IME ne soumet pas accidentellement
- Les thèmes sombre / clair fonctionnent
- La mise en page mobile à 430px, le tiroir de la barre latérale et le tiroir d’informations à droite fonctionnent
- Flux en temps réel SSE : le raisonnement et les deltas de contenu réels de DeepSeek sont visibles avant `done`
- Aucune erreur JS, aucune ressource 404 et aucun 404 WebSocket dans la console (le canal temps réel principal est désormais SSE)

> La vérification réelle en ligne a été effectuée avec la clé DeepSeek référencée par l’assistant IA : `deepseek-flash` a renvoyé `OK`, et le fournisseur/modèle d’utilisation = `deepseek/deepseek-flash`. La clé est stockée uniquement dans `api/configs/secrets_local.py`, qui est ignoré par `.gitignore` ; le dépôt ne versionne que le modèle `secrets_example.py`. Les tests de régression Mock restent en place, de sorte que le système se dégrade automatiquement hors ligne ou sans clé.

---

## 7. Résultats du benchmark équitable Harness

> Dernier rapport : `test/testing/index-2026-10-27.html` (2026-10-27, mimo-v2.6-flash)  
> Rapport historique : `test/testing/index-2026-10-25.html` (2026-10-25, deepseek-flash)

### 7.1 Benchmark équitable MiMo (dernier)

**Méthode** : 5 tâches évaluables automatiquement (1 adaptative de base + 4 couvrant la localisation / les performances / l’horizon long / la concurrence) × 3 outils ; `mimo-v2.6-flash`, prompts, dépôt de départ et budget unifiés. Les tests masqués sont injectés après l’exécution, et `tests/` et `pyproject.toml` sont vérifiés par SHA-256 — toute altération donne un score de 0. t1/d1/d3 utilisent le lot entrelacé officiel-r1 ; d4/d6 utilisent un lot de réexécution indépendant après gel du code.

| Rang | Outil | Global (pondéré par produit) | Exactitude | Vitesse | Coût | Discipline d’ingénierie | Pondération égale |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **98.8** | 100.0 | 94.4 | 96.9 | 100.0 | **98.3 (1er)** |
| 2 | OpenCode | 90.5 | 100.0 | 67.8 | 53.5 | 100.0 | 84.3 (2e) |
| 3 | Claude Code | 88.9 | 100.0 | 65.1 | 40.9 | 100.0 | 81.2 (3e) |

Global = 0.65 × exactitude + 0.15 × vitesse + 0.10 × coût + 0.10 × discipline d’ingénierie ; la formule à pondération égale utilise 0.40 / 0.20 / 0.20 / 0.20.

- Les trois ont obtenu 100 % d’exactitude ; HaoYuan a obtenu **98,8** en pondération par produit et **98,3** en pondération égale, premier selon les deux formules.
- Par tâche : HaoYuan a été le plus rapide sur t1 (63,8 s), d3 (220,6 s) et d4 (469,6 s) ; OpenCode a remporté d1 (111,3 s), et Claude Code a remporté d6 (254,5 s).
- Coût : le coût total des 5 tâches était de **3,33 $** pour HaoYuan, 6,56 $ pour OpenCode et 9,04 $ pour Claude Code ; les coûts par tâche étaient de 0,666 $ / 1,313 $ / 1,809 $.
- Intensité adaptative : t1, une tâche facile, a pris 63,8 s et 11 appels sans lancer de plan ni de sous-agent ; la tâche d4 à long horizon a utilisé du code source pertinent préchargé pour réduire l’exploration répétée (d’un délai d’expiration de 1 200 s à 469,6 s).
- Correctifs clés : fournisseur MiMo finalisé (auparavant, `resolve("mimo", ...)` basculait silencieusement vers deepseek), carte du dépôt tenant compte des exigences, pack de contexte de 30 Ko pour les tâches complexes, récupération de l’arborescence des processus, limites strictes de fournisseur + limites par appel + nouvelles tentatives sur le même modèle, et routage allégé pour les tâches faciles.
- Limites : la comparaison formelle a utilisé 1 tour par tâche ; d4/d6 étaient des lots de réexécution indépendants ; la variance de latence des modèles est importante (Claude sur d3 était à 623 s auparavant et à 884 s cette fois) ; d5 manquait de pouvoir discriminant et n’a pas été classée ; les tâches sont construites en interne et ne peuvent pas remplacer des benchmarks publics tels que SWE-bench.

Reproduire :

```bash
cd test/bench
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks t1_multisite_bugfix,d1_needle_regress,d3_perf_cliff --resume
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks d4_multilayer_feature,d6_concurrency_fix --resume
python make_report_mimo_final.py
```

### 7.2 Benchmark approfondi deepseek-flash (historique)

**Méthode** : 8 tâches de codage évaluables automatiquement (5 basiques + 3 difficiles) × 3 tours par tâche × 3 outils ; deepseek-flash, prompts, dépôt de départ et budget unifiés ; les tests cachés sont injectés après l’exécution, et `tests/` et `pyproject.toml` sont vérifiés par SHA-256 — toute falsification donne un score de 0.

| Rang | Outil | Score global (pondéré par produit) | Exactitude | Vitesse typique | Latence de queue | Coût | Score à pondération égale |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **96,6** | 100,0 | 100,0 (médiane 30,3 s) | 67,6 (P90 159,4 s) | 82,2 (0,364 $) | 95,0 (2e) |
| 2 | OpenCode | 95,1 | 100,0 | 67,6 (médiane 44,8 s) | 100,0 (P90 107,7 s) | 100,0 (0,299 $) | 96,8 (1er) |
| 3 | Claude Code | 90,7 | 100,0 | 70,6 (médiane 42,9 s) | 90,7 (P90 118,7 s) | 55,4 (0,540 $) | 91,7 (3e) |

Score global = 0,70 × exactitude + 0,15 × vitesse typique + 0,05 × latence de queue + 0,10 × coût ; la formule à pondération égale remplace les deux derniers poids par 0,10 / 0,10.

- Les trois ont obtenu 100 % de réponses correctes ; les écarts se concentraient sur la vitesse, la latence de queue et le coût en tokens ; HaoYuan arrivait en tête en pondération produit, tandis qu'OpenCode le dépassait à poids égal.
- HaoYuan présentait le temps médian par tâche le plus court, à 30,3 s, et était le plus rapide sur la médiane de quatre tâches (T1/T2/T3/H1) ; ses 24 exécutions étaient toutes complètes à 100 %. OpenCode avait la meilleure latence de queue et le meilleur coût par tâche ; Claude Code avait le coût en tokens le plus élevé.
- Faiblesses : la migration de version H2 affichait une médiane de 159,4 s (OpenCode : 101,1 s), et H3 présentait une longue queue de 260 s ; les travaux futurs viseront à comprimer davantage les audits de migration et les cycles d'auto-test.
- Limites : couvre uniquement deepseek-flash et 3 tours par tâche ; les tâches sont construites en interne et ne peuvent remplacer des benchmarks publics tels que SWE-bench.
- Auto-itération : durant l'évaluation, l'adaptation aux pipes Windows, la protection contre les réponses vides et l'absence d'écriture, les audits d'acceptation de migration, les audits légers de git diff et l'ordonnancement des finalisations ont été corrigés ; une optimisation négative liée à un « sur-test » a été annulée.

Reproduire :

```bash
cd test/bench
python harness_bench.py run --batch final-r1 --tools haoyuan,claude,opencode --tasks all
python aggregate.py
python make_report.py
```

---

## 8. Parité fonctionnelle avec l'assistant IA

| Capacité | HaoYuan | Remarques |
|---|---|---|
| Chaîne d'outils de codage | ✅ | Localisation, patches minimaux, vérification, boucle de correction, sous-agents |
| Compression de contexte / horizon long | ✅ | Compression en cours de tour, vieillissement, budget strict, points de contrôle, reprise idempotente |
| Parallélisme multi-session | ✅ | Porte de concurrence, FIFO, tâches d'arrière-plan découplées du frontend |
| Porte de permissions / approbation des diffs | ✅ | Cartes d'approbation, aperçu, délai d'expiration, libération de slot de concurrence |
| Bibliothèque de Skills | ✅ | front-matter + règles/BM25 + édition via l'UI |
| Documents de planification | ✅ | Artefacts HTML autonomes |
| Superviseur IA | ✅ | Instantanés, alertes, conversations console, actions planifiées |
| Orchestration multi-agents | ✅ | DAG de tâches + git worktree + métriques de fusion |
| Statistiques de tokens / coûts | ✅ | Agrégation journalière, par modèle, export CSV |
| Mécanisme de plugins | ✅ Amélioré | Manifeste, dépendances, cycle de vie, métadonnées tools/agents/routes/skills/frontend |
| Commande à distance Feishu | ⏳ Pas dans cette version | La couche d'interface est découplée et peut être ajoutée sous forme de plugin |
| ASR / TTS / rendu vidéo | ⏳ Pas dans cette version | L'accent est actuellement mis sur la boucle centrale de codage IA |
| Benchmarks de référence | ⏳ Benchmarks publics non exécutés | Les benchmarks internes sont complets : un benchmark équitable MiMo à 5 tâches et un benchmark approfondi deepseek à 8 tâches (voir section 7) ; les benchmarks publics tels que SWE-bench n'ont pas été réexécutés |

---

## 9. Feuille de route (architecture déjà réservée)

### 9.1 Bibliothèque de Skills pour l'entraînement local sur 16GB VRAM

Éléments prévus :

- Construction de données SFT et scripts d'entraînement pour Qwen3.5-0.8B
- Scripts d'entraînement RL (optimisation des préférences / récompenses vérifiables)
- Configurations économes en mémoire : LoRA / QLoRA, accumulation de gradients, petits lots, contrôle de la longueur de séquence
- Organisés par « skill » : modèles de données, configurations d'entraînement, cas d'évaluation et notes de déploiement

Le mécanisme Skill actuel de HaoYuan est déjà basé sur des fichiers et versionnable ; les documents de méthodologie d'entraînement pourront donc être injectés ultérieurement dans les agents sous forme de Skills.

### 9.2 Harnais embodied basé sur des plugins

`plugins/embodied` démontre déjà :

- Outils d’état du robot / capteurs / mouvement / direction / arrêt d’urgence
- Approbation des actions à haut risque
- Un pont de démonstration HTTP

Sans modifier le noyau, vous pourrez ajouter ultérieurement :

- `embodied-ros2` (topics / services ROS2)
- `embodied-serial` (Arduino / ESP32)
- `embodied-smolvla` (modèle vision-langage-action)
- Plugins Harness pour rovers, bras robotisés et robots humanoïdes

---

## 10. Aperçu de l’API

Préfixe unifié `/api`, format de réponse `{ code, data, message }`.

| Groupe | Principaux points de terminaison |
|---|---|
| Système | `GET /health`, `GET /info`, `GET /models`, `GET /agents`, `GET /tools` |
| Sessions | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `PATCH /sessions/{id}` |
| Messages | `POST /sessions/{id}/messages`, `GET /sessions/{id}/messages` |
| Événements | `GET /sessions/{id}/events?after_id=`, `GET /sessions/{id}/stream`, `WS /ws` |
| Approbations | `GET /approvals`, `POST /approvals/{id}/resolve`, `POST /sessions/{id}/confirm` |
| Compétences | `GET/POST /skills`, `GET/PUT/DELETE /skills/{name}` |
| Fichiers | `GET /workspace/tree`, `GET /workspace/file`, `GET /workspace/changes`, `GET /workspace/diff` |
| Paramètres | `GET/PUT /settings`, `PUT /settings/gate`, `PUT /settings/workspace` |
| Utilisation | `GET /usage/today`, `GET /usage/daily`, `GET /usage/by-model`, `GET /usage/export.csv` |
| Plugins | `GET /plugins`, `POST /plugins/{name}/toggle` |
| Superviseur | `GET /supervisor/overview`, `GET /supervisor/console`, `POST /supervisor/act`, `POST /supervisor/chat` |
| Orchestration | `POST /orchestrations`, `GET /orchestrations`, `GET /orchestrations/{id}` |

Documentation interactive : <http://127.0.0.1:8030/docs> (après une incrémentation du port, utilisez le journal du backend ou `api/data/runtime.json`).

---

## 11. Développement et tests

```bash
cd api
python -m pytest -q

cd ../web
npm run build
npm run dev        # dev mode; /api and /ws proxy to the backend's actual port automatically
```

Nous recommandons d’enregistrer les commandes de lint / test / build de votre équipe dans `AGENTS.md` ; HaoYuan injecte automatiquement la mémoire du projet dans le contexte.

---

## Licence

Ce projet est publié sous la MIT License et peut être utilisé, modifié et distribué librement.
