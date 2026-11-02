# Live TraffiX Hugging Face Space

This root Dockerfile is for the **live TraffiX + SUMO application**. The Compose setup in this
directory remains the separate read-only CoFlow-5 evidence dashboard.

## Build and run locally

From the repository root, build the image and provide an operator token at runtime:

```sh
docker build -t traffix-live .
docker run --rm -p 7860:7860 -e TRAFFIX_OPERATOR_TOKEN=choose-a-long-random-value traffix-live
```

Open `http://localhost:7860`. Enter the token in the Operator token field before starting or
stopping a run or injecting an event. Health is available at `/health`. The container runs a single
Uvicorn worker because the live run is process-local and only one simulation may own TraCI. Each
run is capped at one hour of wall-clock time; speed, seed and incident duration/count are bounded.

## Configure the Hugging Face Space

1. Create a **Docker Space** from a branch containing the root `Dockerfile` and this README metadata.
2. Add `TRAFFIX_OPERATOR_TOKEN` in Space Settings → Variables and secrets as a **Secret**. The
   container exits at startup if it is absent; do not add the value to Git or the Docker build.
3. Begin with CPU hardware. Check current account credits and billing before selecting an upgrade.
4. Keep the Space private or restrict who can visit it for the presentation.
5. Check the build logs and `/health`, then rehearse start → inject → observe → stop from a separate
   browser. The live Space uses one process and one active shared simulation.
6. Pause the Space when the demo is over. Disk is ephemeral; copy any results worth retaining to
   the Hub or a persistent Storage Bucket.

Training/evaluation are separate Hugging Face Jobs, not part of this Space. Give each Job a timeout,
use held-out evaluation seeds and upload artifacts before it terminates.

## Safety and known limits

- The operator token protects start, stop, event injection, copilot/LLM requests and recorded
  copilot decisions.
- Supported runtime injection is currently a simulated stalled vehicle on a validated passenger
  lane. No real infrastructure is connected or controlled.
- The Space currently runs one shared demo; it is not a multi-user session manager.
- Confirm permission to redistribute adopted `traffix3` code and comply with OSM, basemap and
  community transit-data attribution/licensing before making the Space public.
