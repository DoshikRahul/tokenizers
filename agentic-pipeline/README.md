# SOAP note generation

Keep the Qwen endpoint and SSH tunnel running at `http://127.0.0.1:8001/v1`.

Run the full dataset in a screen:

```bash
cd /home/surya/Desktop/tokenizers/agentic-pipeline
screen -S soap-generation
bash generate_soap.sh --resume latest
```

Detach with **Ctrl+a**, then **d**. Reattach later with:

```bash
screen -r soap-generation
```

Check progress from another terminal:

```bash
cd /home/surya/Desktop/tokenizers/agentic-pipeline
bash generate_soap.sh --status
```

If the process stops, run the same `--resume latest` command again. Completed encounters are skipped; unfinished or failed encounters continue from their saved checkpoint. The model client also compacts derived prompts and lowers the response budget when the endpoint reports a context-limit error.

Final files are written directly here:

```text
/home/surya/Desktop/tokenizers/agentic-pipeline-output/soap_notes/D2N001/
  soap_note.md
  soap_note.json
  consultation.md
  agent_conversation.md
```

Checkpoint files and raw logs are kept in the ignored `agentic-pipeline-output-backups/` folder so the public output stays clean.
