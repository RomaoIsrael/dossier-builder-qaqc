"""Modelo de datos para un documento (PDF) insertado en una seccion del dossier."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class SignatureTreatment(str, Enum):
    """Que hacer con un documento respecto a sus firmas al incorporarlo al dossier."""

    KEEP_ORIGINAL = "keep_original"
    FLATTEN = "flatten"
    AUTO = "auto"


class DocumentStatus(str, Enum):
    """Estado de un documento dentro del proyecto (previo o posterior a la generacion)."""

    PENDING = "pending"
    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"
    PASSWORD_PROTECTED = "password_protected"
    FLATTENED = "flattened"
    ERROR = "error"


@dataclass
class DocumentItem:
    """Un archivo PDF (o resultado de aplanado) que se insertara en una seccion."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_path: str = ""
    display_name: str = ""
    order: int = 0

    signature_treatment: SignatureTreatment = SignatureTreatment.AUTO
    has_signature: Optional[bool] = None
    signature_details: list[str] = field(default_factory=list)

    status: DocumentStatus = DocumentStatus.PENDING
    error_message: Optional[str] = None

    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    sha256_original: Optional[str] = None

    # Se completan solo cuando el documento requiere aplanado (firma visible).
    flattened_path: Optional[str] = None
    sha256_flattened: Optional[str] = None
    flatten_dpi: Optional[int] = None

    @property
    def name(self) -> str:
        return self.display_name or (Path(self.source_path).name if self.source_path else "(sin nombre)")

    @property
    def will_be_flattened(self) -> bool:
        if self.signature_treatment == SignatureTreatment.FLATTEN:
            return True
        if self.signature_treatment == SignatureTreatment.AUTO:
            return bool(self.has_signature)
        return False

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["signature_treatment"] = self.signature_treatment.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentItem":
        data = dict(data)
        data["signature_treatment"] = SignatureTreatment(data.get("signature_treatment", "auto"))
        data["status"] = DocumentStatus(data.get("status", "pending"))
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
