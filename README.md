# Video2Gauss — Video to 3D Reconstruction Website

Upload a video, get a 3D point cloud model you can freely browse in your browser. Powered by [lingbot-map](https://github.com/Robbyant/lingbot-map) (Geometric Context Transformer).

## Architecture

```
Browser (React + Three.js)
  → Ingress (Sealos)
    → Frontend (Nginx, port 80)
    → Backend (FastAPI, port 8000)
      → PostgreSQL (job tracking)
      → Redis (queue + pub/sub)
      → MinIO (video + GLB storage)
      → GPU Worker (lingbot-map inference, CUDA)
```

## Quick Start (Local Dev)

```bash
# 1. Clone with submodules
git clone --recurse-submodules https://github.com/ljx0722/video-3d-reconstruction.git
cd video-3d-reconstruction

# 2. Start all services
docker compose up -d

# 3. Start frontend dev server (hot reload)
cd frontend && npm install && npm run dev

# 4. Start backend dev server
cd backend && pip install -e . && uvicorn app.main:app --reload

# Open http://localhost:5173
```

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/jobs.db` | Database connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for job queue |
| `MINIO_ENDPOINT` | `localhost:9000` | Object storage endpoint |
| `MINIO_BUCKET` | `video-3d` | Storage bucket name |

## Deploy to Sealos

The GitHub Actions workflow (`.github/workflows/deploy.yml`) auto-deploys on push to `main`:

1. Builds Docker images for frontend, backend, and GPU worker
2. Pushes to `ghcr.io/ljx0722/video-3d-reconstruction-*`
3. Applies Kubernetes manifests from `deploy/sealos/`
4. Updates deployments and verifies rollout

Required GitHub Secrets:
- `GITHUB_TOKEN` — for pushing to ghcr.io
- `SEALOS_KUBECONFIG` — base64-encoded kubeconfig for Sealos cluster

## Project Structure

```
├── frontend/          # React + TypeScript + Vite + Three.js
├── backend/           # Python FastAPI + SQLAlchemy
├── gpu_worker/        # lingbot-map inference worker (CUDA GPU)
├── deploy/sealos/     # Kubernetes manifests
├── docker-compose.yml # Local dev stack
└── .github/workflows/ # CI/CD pipeline
```

## License

This project is licensed under Apache 2.0. The lingbot-map model is from [Robbyant/lingbot-map](https://github.com/Robbyant/lingbot-map).
