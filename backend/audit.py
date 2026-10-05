from __future__ import annotations

import json
from typing import Any
from db import db


def audit_event(user_id: int | None, event_type: str, metadata: dict[str, Any] | None = None) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO audit_log(user_id,event_type,metadata_json) VALUES(?,?,?)",
            (user_id, event_type, json.dumps(metadata or {}, separators=(",", ":"), default=str)),
        )
