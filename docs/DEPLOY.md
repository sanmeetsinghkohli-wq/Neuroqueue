# Deploying NeuroQueue

## Backend container

```bash
docker build -f backend/Dockerfile -t neuroqueue-api .
docker run -p 8000:8000 --env-file backend/.env neuroqueue-api
```

Run **one** instance: the realtime hub and the job framework live in the process. For more than one instance, put a
shared pub/sub (for example Redis) behind `app/realtime.py`.

### Alibaba Cloud ECS
1. Push the image to Container Registry (ACR) and pull it on an ECS instance (2 vCPU / 4 GB is enough; inference is CPU).
2. Provide the variables from `backend/.env.example` as environment variables, never in the image.
3. Put an SLB or Nginx with TLS in front. WebSocket upgrade must be allowed on `/ws`.
4. Set `CORS_ORIGINS` to the frontend origin.

### Alibaba Cloud Function Compute
Use a custom-container HTTP function with the same image, instance concurrency above 1, a minimum of one provisioned
instance (to keep the WebSocket hub and the loaded model warm) and WebSocket enabled on the HTTP trigger.

## Storage
- Default: Supabase Storage bucket `scans` (private), created by `supabase/schema.sql`.
- OSS option: add a store that implements `put_file`, `get_file` and `delete_file` from `backend/app/store/base.py`
  with the `oss2` SDK and select it in `backend/app/store/__init__.py`. Nothing else in the code touches storage.

## Frontend
`npm run build && npm start`, or any Next.js host. Set `NEXT_PUBLIC_API_URL` to the public backend URL at build time.

## Before a demo
- `python seed.py`, then sign in once with each account.
- Load the 20 demo scans and process them once to confirm Qwen is reachable. If the network is unreliable, switch on
  `NQ_MOCK_MODE=true`: the flow still runs end to end with the mock providers.
- Screenshot list for the pitch: landing hero, queue before and after processing, review with heatmap, blocked report
  check, signed report with PDF, metrics (confusion matrix, calibration, simulation), audit chain verified, admin
  approvals, patient report view, help assistant in voice mode.

## Vercel (site) + a container host (API)

Vercel runs the Next.js site only. The API cannot run there: it keeps WebSocket connections open, holds the live
queue hub in memory and loads the ONNX model, none of which fit serverless functions. Run the API as one long-lived
container (Render, Railway, Fly.io, ECS) from `backend/Dockerfile`.

How the two halves talk:
- The browser calls `/api/...` on the site's own address; `next.config.ts` forwards those to `BACKEND_URL`. The session
  cookie therefore belongs to the site's own domain and works in every browser.
- The live connection goes straight to the API (`NEXT_PUBLIC_WS_URL`) using a one-time, 30-second ticket.

Vercel project settings: root directory `frontend`, then environment variables
- `BACKEND_URL` = `https://<your-api-host>`
- `NEXT_PUBLIC_WS_URL` = `wss://<your-api-host>/ws`

API environment (in addition to the keys in `backend/.env.example`)
- `APP_URL` = `https://<your-site>.vercel.app` (links in verification and reset emails)
- `CORS_ORIGINS` = `https://<your-site>.vercel.app`
- `COOKIE_SECURE=true`, `TRUST_PROXY=true`

Google sign-in: add `https://<your-site>.vercel.app` to the OAuth client's Authorized JavaScript origins.
