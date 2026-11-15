from .prompts import patient_prompt


class PatientAgent:
    """Owns the source transcript separately from all doctor graph state."""
    def __init__(self, dialogue: str, client, log):
        self.__system = patient_prompt(dialogue)
        self.client = client
        self.log = log

    async def answer(self, history: list[dict]) -> str:
        return await self.client.complete(
            agent="patient", phase="historytaking", system=self.__system,
            payload={"simulated_consultation": history[-10:], "instruction": "Answer only the latest doctor's question, using your case information."},
            output=None, max_tokens=512, temperature=0.1, log=self.log,
        )
