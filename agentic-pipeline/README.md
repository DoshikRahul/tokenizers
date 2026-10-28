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
processes all 207 encounters. Open the simple final view here:

```text
/home/surya/Desktop/tokenizers/agentic-pipeline-output/soap_notes/
  D2N001/
    soap_note.md
    soap_note.json
    consultation.md
    agent_conversation.md
  D2N002/
  ...
  SUMMARY.json
```

There is one folder per encounter. `soap_note.md` is the readable note;
`agent_conversation.md` contains the agent exchanges. `SUMMARY.json` records
the source split for each encounter.

Detach: **Ctrl+a**, then **d**. Return: `screen -r soap-generation`.

To continue after stopping (stop the previous process first):

```bash
bash generate_soap.sh --resume
```

This resumes the latest technical run folder, skips completed notes, retries
failed encounters, and reuses saved questions and patient answers. An unfinished
doctor-team turn may run again. To resume the preserved technical run from the backup folder, use:

```bash
bash generate_soap.sh --resume /home/surya/Desktop/tokenizers/agentic-pipeline-output-backups/20261026T135032Z_bcaa84db
```

Running without `--resume` starts a new run.

Optional connection check or single-encounter run:

```bash
bash generate_soap.sh --check
bash generate_soap.sh --split train --encounter-id D2N001
```
