from typing import Literal
from pydantic import BaseModel, ConfigDict


class RecordingReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    storage_type: Literal["local"] = "local"
    object_key: None = None


def recording_reference(call) -> RecordingReference:
    """Current ingestion only writes local files. Never export audio_path.

    A future private-S3 adapter must verify persisted upload completion and
    an explicit export setting before returning a private object key.
    """
    return RecordingReference()
