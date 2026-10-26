# Qwen3-14B: download, serve, and connect

Use four RTX 2080 Ti GPUs, Python 3.10-3.12, and about 60 GB free disk space.
The `screen` command should be available on the GPU server and your local Linux system.

## 1. Copy the folder

Copy the whole `Qwen3-14B_setup` folder to the GPU server at:

```text
/scratch/jyothika.goparaju/Qwen3-14B_setup
```

The folder includes `req.txt`, `host.py`, and `run.sh`.

## 2. Download the model — on gnode088

```bash
cd /scratch/jyothika.goparaju/Qwen3-14B_setup
bash run.sh --setup-only
```

This creates `.venv`, installs requirements, and downloads the model.
Run this once; it does not start the endpoint.

## 3. Start inference inside screen — on gnode088

If moving an already running server into screen, stop the old server with
`Ctrl+C` first. Run only one server instance.

Create a screen session:

```bash
screen -S qwen-server
```

Inside that screen, run:

```bash
cd /scratch/jyothika.goparaju/Qwen3-14B_setup
bash run.sh --serve-only
```

Wait for `Endpoint ready` and `Uvicorn running on http://127.0.0.1:8000`.
Then detach: press `Ctrl+a`, release, then press `d`.
The server keeps running after detaching.

To return later:

```bash
screen -r qwen-server
```

## 4. Test on gnode088 — after detaching

Health:

```bash
curl --fail-with-body http://127.0.0.1:8000/health
```

Look for `"status":"ready"` and `"gpu_count":4`.

Sample inference:

```bash
curl --fail-with-body http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3-14B","messages":[{"role":"user","content":"Reply with one sentence confirming you are ready."}],"max_tokens":64,"temperature":0}'
```

## 5. Port forward inside screen — on your local Linux system

Open a terminal on your own computer, not inside the GPU SSH session.
If the same tunnel is already running outside screen, stop that tunnel with
`Ctrl+C` first so local port 8001 is available.

Create a local screen session:

```bash
screen -S qwen-tunnel
```

Inside that screen, run:

```bash
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -J jyothika.goparaju@ada-gw1.iiit.ac.in \
  -L 127.0.0.1:8001:127.0.0.1:8000 \
  jyothika.goparaju@gnode088
```

Enter the gateway and GPU SSH passwords when prompted. Once connected, there
is no shell prompt; SSH stays running. Detach with `Ctrl+a`, then `d`.
Local port **8001** now forwards to port **8000** on gnode088.

To return later:

```bash
screen -r qwen-tunnel
```

Keep both screen sessions running. Screen survives terminal disconnection;
it does not restart a failed SSH tunnel or a stopped model server.

## 6. Test from your local Linux system — after detaching

Health:

```bash
curl --fail-with-body http://127.0.0.1:8001/health
```

Sample inference:

```bash
curl --fail-with-body http://127.0.0.1:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3-14B","messages":[{"role":"user","content":"Reply with one sentence confirming you are ready."}],"max_tokens":64,"temperature":0}'
```

## 7. Request and response JSON

Request body for `POST http://127.0.0.1:8001/v1/chat/completions`:

```json
{
  "model": "Qwen3-14B",
  "messages": [
    {
      "role": "user",
      "content": "Reply with one sentence confirming you are ready."
    }
  ],
  "max_tokens": 64,
  "temperature": 0
}
```

Example response; IDs, timestamps, token counts, and wording can vary:

```json
{
  "id": "chatcmpl-80b5b06887fd499bb72b445cd7023aa1",
  "object": "chat.completion",
  "created": 1793009714,
  "model": "Qwen3-14B",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "I am ready."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 21,
    "completion_tokens": 5,
    "total_tokens": 26
  }
}
```

The answer is in `choices[0].message.content`.

Local pipeline settings:

```text
Base URL: http://127.0.0.1:8001/v1
Model: Qwen3-14B
API key: local-unused
```

The default setup needs no API key; `local-unused` is a placeholder for clients
that require one. If you set `MODEL_API_KEY` on the server, use that value and
add `Authorization: Bearer <your-key>` to requests.

The server handles one generation at a time, with an 8,192-token total context
and up to 2,048 output tokens. Requests use non-streaming responses.
