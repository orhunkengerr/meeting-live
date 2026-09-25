"""Translate sentences with Google's free translate endpoint (no API key).

Uses only the standard library. When the request fails the caller gets None
and can still show the original text, so a network hiccup never blocks the
subtitles.
"""

import json
import urllib.parse
import urllib.request

ENDPOINT = "https://translate.googleapis.com/translate_a/single"


class Translator:
    def __init__(self, target: str, timeout: float = 5.0):
        self.target = target
        self.timeout = timeout

    def translate(self, text: str, source: str | None = None) -> str | None:
        """Translate text into the target language.

        Returns None when there is nothing to do (empty text, or already in the
        target language) or when the request fails.
        """
        if not text.strip() or source == self.target:
            return None
        query = urllib.parse.urlencode({
            "client": "gtx",
            "sl": source or "auto",
            "tl": self.target,
            "dt": "t",
            "q": text,
        })
        try:
            with urllib.request.urlopen(f"{ENDPOINT}?{query}", timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            # data[0] is a list of [translated, original, ...] pieces, one per sentence.
            return "".join(piece[0] for piece in data[0] if piece[0]).strip() or None
        except (OSError, ValueError, IndexError, TypeError):
            return None


if __name__ == "__main__":
    print(Translator("tr").translate("Can you send me the report by Friday?", "en"))
