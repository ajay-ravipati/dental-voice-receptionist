"""Strict argument validation for every tool the voice model may call (pydantic v2)."""
from __future__ import annotations

import re
from datetime import date as _date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,59}$")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def normalize_phone(v) -> str:
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ValueError("phone must be a 10-digit Indian mobile number starting with 6, 7, 8 or 9")
    return digits


def _iso(v) -> str:
    try:
        return _date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise ValueError("date must be in YYYY-MM-DD format")


def _hhmm(v) -> str:
    m = _TIME_RE.match(str(v).strip())
    if not m:
        raise ValueError("time must be 24-hour HH:MM, e.g. 15:30")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _short(v, n=80) -> str:
    s = str(v).strip()
    if len(s) > n:
        raise ValueError(f"must be at most {n} characters")
    return s


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class InfoArgs(_Base):
    topic: Literal["overview", "hours", "location", "services", "pricing", "doctors", "payment",
                   "insurance", "parking", "policies", "first_visit", "contact"]
    service: Optional[str] = None

    @field_validator("service")
    @classmethod
    def v_svc(cls, v):
        return _short(v) if v else v


class AvailabilityArgs(_Base):
    date: str
    treatment: Optional[str] = None
    doctor: Optional[str] = None

    @field_validator("date", mode="before")
    @classmethod
    def v_date(cls, v):
        return _iso(v)

    @field_validator("treatment", "doctor")
    @classmethod
    def v_opt(cls, v):
        return _short(v) if v else v


class BookArgs(_Base):
    patient_name: str
    phone: str
    date: str
    time: str
    treatment: str
    is_new_patient: bool = True
    caller_confirmed: bool = False
    doctor: Optional[str] = None

    @field_validator("patient_name")
    @classmethod
    def v_name(cls, v):
        v = " ".join(str(v).split())
        if not _NAME_RE.match(v):
            raise ValueError("patient_name must be a real name (letters only, 2-60 chars)")
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def v_phone(cls, v):
        return normalize_phone(v)

    @field_validator("date", mode="before")
    @classmethod
    def v_date_iso(cls, v):
        return _iso(v)

    @field_validator("time", mode="before")
    @classmethod
    def v_time(cls, v):
        return _hhmm(v)

    @field_validator("treatment", "doctor")
    @classmethod
    def v_opt(cls, v):
        return _short(v) if v else v


class LookupArgs(_Base):
    phone: str
    patient_name: str

    @field_validator("phone", mode="before")
    @classmethod
    def v_phone(cls, v):
        return normalize_phone(v)

    @field_validator("patient_name")
    @classmethod
    def v_name(cls, v):
        v = " ".join(str(v).split())
        if not _NAME_RE.match(v):
            raise ValueError("patient_name must be a real name")
        return v


class CancelArgs(_Base):
    booking_id: str
    phone: str

    @field_validator("phone", mode="before")
    @classmethod
    def v_phone(cls, v):
        return normalize_phone(v)

    @field_validator("booking_id")
    @classmethod
    def v_bid(cls, v):
        v = re.sub(r"[\s]", "", str(v)).upper()
        if not re.fullmatch(r"SC-?[A-Z0-9]{4}", v):
            raise ValueError("booking_id looks like SC-7K2P")
        return v if "-" in v else f"SC-{v[2:]}"


class RescheduleArgs(CancelArgs):
    new_date: str
    new_time: str

    @field_validator("new_date", mode="before")
    @classmethod
    def v_nd(cls, v):
        return _iso(v)

    @field_validator("new_time", mode="before")
    @classmethod
    def v_nt(cls, v):
        return _hhmm(v)


class EscalateArgs(_Base):
    reason: str
    callback_phone: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def v_r(cls, v):
        return _short(v, 200)

    @field_validator("callback_phone", mode="before")
    @classmethod
    def v_p(cls, v):
        return normalize_phone(v) if v else None


class EmergencyArgs(_Base):
    symptoms: str

    @field_validator("symptoms")
    @classmethod
    def v_s(cls, v):
        return _short(v, 300)


TOOL_MODELS = {
    "get_clinic_info": InfoArgs,
    "check_availability": AvailabilityArgs,
    "book_appointment": BookArgs,
    "lookup_appointments": LookupArgs,
    "cancel_appointment": CancelArgs,
    "reschedule_appointment": RescheduleArgs,
    "request_callback": EscalateArgs,
    "flag_dental_emergency": EmergencyArgs,
}
