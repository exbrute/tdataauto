from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelPostRef:
    peer: str | int
    msg_id: int


_POST_LINK = re.compile(
    r"^https?://(?:t(?:elegram)?\.me|telegram\.dog)/(?:(c)/(\d+)/(\d+)|([\w_]+)/(\d+))/?(?:\?.*)?$",
    re.IGNORECASE,
)


def parse_channel_post_url(url: str) -> ChannelPostRef:
    url = url.strip()
    match = _POST_LINK.match(url)
    if not match:
        raise ValueError(
            "Неверная ссылка. Нужен пост канала, например "
            "https://t.me/my_channel/42 или https://t.me/c/1234567890/42"
        )
    if match.group(1):
        internal_id = int(match.group(2))
        msg_id = int(match.group(3))
        return ChannelPostRef(peer=int(f"-100{internal_id}"), msg_id=msg_id)
    username = match.group(4)
    msg_id = int(match.group(5))
    return ChannelPostRef(peer=username, msg_id=msg_id)
