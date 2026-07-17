# Mock Manager

Toggle environment variables across Kubernetes deployments from a single UI.

**Architecture:** Flutter UI → FastAPI → kubectl → Teleport → Kubernetes API

**Cluster access:** Teleport 17 (pre-installed in Docker image, `tsh login` required before use)

## Quick start (Docker)

```bash
# 1. Clone and enter
git clone <repo-url> mock-manager && cd mock-manager

# 2. Configure
cp backend/.env.example backend/.env
# Edit backend/.env: set K8S_NAMESPACE, KUBECONFIG path

# 3. Build frontend (requires Flutter SDK)
cd ui/mock_manager_flutter && flutter build web && cd ../..

# 4. Run
docker compose up --build
```

Open http://localhost

## Local development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd ui/mock_manager_flutter
flutter pub get
flutter run -d chrome   # or -d macos / -d windows / -d linux
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `K8S_NAMESPACE` | `payment-cards` | Kubernetes namespace |
| `KUBECONFIG` | `~/.kube/config` | Path to kubeconfig file |
| `DATABASE_URL` | `sqlite:///./mock_manager.db` | SQLite DB path |
| `DEBUG` | `false` | Enable debug logging |
| `SLACK_WEBHOOK_URL` | — | Slack webhook for notifications |
| `BAND_WEBHOOK_URL` | — | Band webhook for notifications |
| `SECRET_KEY` | `change-me-in-production` | App secret key |

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/variables/` | List tracked variables |
| POST | `/api/variables/` | Add variable |
| GET | `/api/groups/` | List groups |
| POST | `/api/groups/` | Create group |
| POST | `/api/groups/update` | Toggle group |
| GET | `/api/services/` | List services with env vars |
| POST | `/api/services/update` | Update service variable |
| GET | `/api/services/logs` | Change history |
| WS | `/api/services/ws` | Real-time updates |

## Project structure

```
mock-manager/
├── docker-compose.yml      # Production deployment
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + lifecycle
│   │   ├── config.py        # Env-based configuration
│   │   ├── api/             # REST + WebSocket routes
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── k8s_client_kubectl.py  # kubectl wrapper
│   │   ├── k8s_watcher.py   # Real-time K8s change watcher
│   │   └── notifiers/       # Slack, Band webhooks
│   ├── tests/
│   ├── Dockerfile           # Installs Python + Teleport
│   └── .env.example
└── ui/
    └── mock_manager_flutter/
        ├── lib/
        │   ├── screens/     # UI pages
        │   ├── services/    # API, WebSocket, config
        │   ├── providers/   # State management
        │   ├── models/      # Data models
        │   └── widgets/     # Reusable components
        ├── Dockerfile       # nginx serving Flutter web build
        └── pubspec.yaml
```

## Usage

1. **Variables** — add env vars you want to control (e.g. `MOCK_ENABLED`, `USE_MOCK`)
2. **Groups** — group services + variables by feature
3. **Toggle** — flip all mocks in a group with one switch
4. **Logs** — audit trail of every change (who, when, what)
