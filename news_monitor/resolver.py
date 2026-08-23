import json
import logging
import re
from urllib.parse import urlparse

from .config import REQUEST_TIMEOUT
from .http import build_session
from .text import canonicalize_url

logger = logging.getLogger(__name__)
BATCH_EXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


class GoogleNewsResolver:
    """Resolve modern Google News RSS wrappers to publisher URLs."""

    def __init__(self) -> None:
        self.session = build_session()

    def resolve(self, url: str) -> str:
        if "news.google.com" not in urlparse(url).netloc.casefold():
            return canonicalize_url(url)

        article_id = url.rstrip("/").split("/")[-1].split("?", 1)[0]
        if not article_id:
            return ""

        try:
            page = self.session.get(url, timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
            signature_match = re.search(r'data-n-a-sg="([^"]+)"', page.text)
            timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', page.text)
            if not signature_match or not timestamp_match:
                return ""

            inner_request = json.dumps(
                [
                    "garturlreq",
                    [
                        [
                            "X", "X", ["X", "X"], None, None, 1, 1,
                            "ID:id", None, 1, None, None, None, None,
                            None, 0, 1,
                        ],
                        "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0,
                        None, 0,
                    ],
                    article_id,
                    int(timestamp_match.group(1)),
                    signature_match.group(1),
                ],
                separators=(",", ":"),
            )
            request_payload = json.dumps(
                [[["Fbv4je", inner_request, None, "generic"]]],
                separators=(",", ":"),
            )
            response = self.session.post(
                BATCH_EXECUTE_URL,
                data={"f.req": request_payload},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Referer": "https://news.google.com/",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return self._parse_response(response.text)
        except Exception as exc:
            logger.info("Google News URL resolution failed: %s", exc)
            return ""

    @staticmethod
    def _parse_response(body: str) -> str:
        if body.startswith(")]}'"):
            body = body.split("\n", 1)[1]
        body = body.lstrip()
        head, separator, tail = body.partition("\n")
        if separator and head.strip().isdigit():
            body = tail

        try:
            envelopes = json.loads(body)
        except json.JSONDecodeError:
            return ""

        for envelope in envelopes:
            if (
                isinstance(envelope, list)
                and len(envelope) >= 3
                and envelope[0] == "wrb.fr"
                and envelope[1] == "Fbv4je"
            ):
                try:
                    payload = json.loads(envelope[2])
                except (TypeError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(payload, list)
                    and len(payload) >= 2
                    and payload[0] == "garturlres"
                ):
                    return canonicalize_url(str(payload[1]))
        return ""
