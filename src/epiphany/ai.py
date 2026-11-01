import logging

from openai import AsyncOpenAI

from .content import BadAnswer, LongContent, ShortContent, parse
from .prompts import SYSTEM, long_description_prompt, short_description_prompt

logger = logging.getLogger(__name__)


class GenerationError(Exception):
    pass


class ContentGenerator:
    """Asks the model for the two JSON answers. The old code called ``openai.ChatCompletion``
    (gone from the current SDK) from a thread pool, with ``gpt-4`` hard-coded and a sleep for rate
    limits; the SDK now retries rate limits itself and the model is a setting."""

    def __init__(self, client: AsyncOpenAI, model, attempts=2):
        self.client, self.model, self.attempts = client, model, max(1, attempts)

    async def _ask(self, prompt, model_class, what):
        last = None
        for attempt in range(1, self.attempts + 1):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            text = response.choices[0].message.content if response.choices else None
            try:
                return parse(model_class, text)
            except BadAnswer as error:
                last = error
                logger.warning(
                    "The %s answer was not usable (attempt %d): %s", what, attempt, error
                )
        raise GenerationError(f"no usable {what} from the model: {last}")

    async def short(self, title, short_description, categories_string):
        prompt = short_description_prompt(title, short_description, categories_string)
        return await self._ask(prompt, ShortContent, "short description")

    async def long(self, title, long_description):
        prompt = long_description_prompt(title, long_description)
        return await self._ask(prompt, LongContent, "long description")
