# Generate SOAP notes

Keep the GPU model server and SSH tunnel running (`http://127.0.0.1:8001/v1`).
Run on your local computer:

```bash
screen -S soap-generation
```

Inside the screen:

```bash
cd /home/surya/Desktop/tokenizers/agentic-pipeline
bash generate_soap.sh
```

The script creates/activates `.venv`, installs requirements when needed, and
processes all 207 encounters. Notes and agent conversations are saved in
`/home/surya/Desktop/tokenizers/agentic-pipeline-output/<run-id>/`.

Detach: **Ctrl+a**, then **d**. Return: `screen -r soap-generation`.

To continue after stopping (stop the previous process first):

```bash
bash generate_soap.sh --resume
```

This resumes the latest run in the same folder, skips completed notes, retries
failed encounters, and reuses saved questions and patient answers. An unfinished
doctor-team turn may run again. To select an older run, add its folder after `--resume`.
Running without `--resume` starts a new run.

Optional connection check or single-encounter run:

```bash
bash generate_soap.sh --check
bash generate_soap.sh --split train --encounter-id D2N001
```
