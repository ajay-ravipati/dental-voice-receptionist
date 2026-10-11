"""Details about clinic"""
from __future__ import annotations
import hashlib
import re
import secrets
import threading
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

CLINIC = {
    "name": "SmileCraft Dental Studio",
    "address": "No. 42, 12th Main Road, HAL 2nd Stage, Indiranagar, Bengaluru 560038",
    "landmark": "About a ten-minute walk from Indiranagar Metro station",
    "phone": "+91 80 4000 0000",
}

SLOT_TIMES = (
    ["09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00"]
    + ["14:30", "15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00"]
)

DOCTORS = {
    "rao": {"name": "Dr. Ananya Rao", "title": "general and cosmetic dentist", "days": {0, 1, 2, 3, 4, 5}},
    "iyer": {"name": "Dr. Karthik Iyer", "title": "endodontist and implant specialist", "days": {0, 2, 4, 5}},
    "nair": {"name": "Dr. Meera Nair", "title": "orthodontist", "days": {1, 3, 5}},
}
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

ALL_DOCS = ["rao", "iyer", "nair"]
SERVICES = {
    "consultation": dict(name="check-up and consultation", min=500, max=500, docs=ALL_DOCS,
                         note="Includes a full oral examination and a treatment plan."),
    "scaling": dict(name="scaling and polishing", min=1500, max=2500, docs=["rao"], note=""),
    "whitening": dict(name="teeth whitening", min=8000, max=15000, docs=["rao"], note=""),
    "filling": dict(name="tooth-coloured filling", min=1200, max=3000, docs=["rao", "iyer"], note="Price is per tooth."),
    "root_canal": dict(name="root canal treatment", min=4500, max=9000, docs=["iyer"],
                       note="A crown is usually advised afterwards and is charged separately. May take more than one sitting."),
    "crown": dict(name="dental crown", min=7000, max=12000, docs=["rao", "iyer"], note="Price is per tooth."),
    "extraction": dict(name="tooth extraction", min=1000, max=2500, docs=["rao", "iyer"], note="Simple extraction."),
    "wisdom_tooth": dict(name="wisdom tooth removal", min=4000, max=9000, docs=["iyer"], note="Surgical removal."),
    "implant": dict(name="dental implant", min=28000, max=45000, docs=["iyer"], note="Per implant, crown included."),
    "braces": dict(name="metal braces", min=35000, max=60000, docs=["nair"], note="Full treatment."),
    "aligners": dict(name="clear aligners", min=90000, max=200000, docs=["nair"], note="Depends on case complexity."),
    "kids": dict(name="children's dental check-up", min=500, max=500, docs=["rao"], note=""),
    "xray": dict(name="dental X-ray", min=200, max=1200, docs=ALL_DOCS,
                 note="A small single-tooth X-ray is about 200 to 300 rupees; a full-mouth panoramic X-ray is about 800 to 1,200."),
    "emergency": dict(name="urgent pain or emergency visit", min=500, max=500, docs=ALL_DOCS,
                      note="Consultation fee; any treatment is extra."),
}

_KEYWORDS = [
    ("root_canal", r"root\s*canal|rct|nerve"),
    ("wisdom_tooth", r"wisdom"),
    ("implant", r"implant"),
    ("aligners", r"aligner|invisalign|clear (brace|align)"),
    ("braces", r"brace|orthodon|straighten|crooked"),
    ("whitening", r"whiten|bleach"),
    ("scaling", r"scaling|cleaning|polish|tartar"),
    ("crown", r"crown|cap\b"),
    ("filling", r"fill|cavity|cavities|decay"),
    ("extraction", r"extract|remove|pull(ing)? (a )?tooth"),
    ("xray", r"x-?ray|opg|radiograph"),
    ("kids", r"child|kid|paediatric|pediatric|my (son|daughter)"),
    ("emergency", r"emergency|urgent|severe pain|toothache|tooth ache|swelling|broken tooth|knocked"),
    ("consultation", r"consult|check-?up|checkup|examin|general|visit|first time|second opinion"),
]


def resolve_service(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for key, pat in _KEYWORDS:
        if re.search(pat, t):
            return key
    return None


def resolve_doctor(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for k, d in DOCTORS.items():
        if k in t or d["name"].lower().split()[-1] in t:
            return k
    return None


def inr(n: int) -> str:
    s = str(int(n))
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts + [tail])


def price_text(key: str) -> str:
    s = SERVICES[key]
    p = inr(s["min"]) if s["min"] == s["max"] else f"{inr(s['min'])} to {inr(s['max'])}"
    extra = f" {s['note']}" if s["note"] else ""
    return f"{s['name'].capitalize()}: {p}.{extra}"


def known_price_numbers() -> set[int]:
    """Every rupee figure the bot may legitimately quote (used by the output guardrail)."""
    nums = {200, 300, 800, 1200, 500, 20000, 10000}
    for s in SERVICES.values():
        nums.update({s["min"], s["max"]})
    return nums


# ---- knowledge base
def get_clinic_info(topic: str, service: Optional[str] = None) -> dict:
    if topic == "pricing":
        key = resolve_service(service)
        if key:
            text = price_text(key)
        else:
            text = " ".join(price_text(k) for k in
                            ["consultation", "scaling", "filling", "root_canal", "extraction", "implant", "braces"])
            text += " Ask for any other treatment by name."
        info = text + " These are indicative prices; the dentist confirms the exact cost after examining you."
    elif topic == "services":
        info = "We offer " + ", ".join(s["name"] for k, s in SERVICES.items() if k != "emergency") + "."
    elif topic == "hours":
        info = ("Open Monday to Saturday, 9:30 AM to 7:30 PM, with a lunch break from 1:30 to 2:30 PM. "
                "Closed on Sundays and public holidays. For urgent problems on a Sunday, please go to the nearest "
                "hospital emergency department.")
    elif topic in ("location", "contact"):
        info = (f"{CLINIC['name']}, {CLINIC['address']}. {CLINIC['landmark']}. "
                f"Front desk phone: {CLINIC['phone']}.")
    elif topic == "doctors":
        info = " ".join(
            f"{d['name']}, {d['title']}, available on {', '.join(_DAY_NAMES[i] for i in sorted(d['days']))}."
            for d in DOCTORS.values())
    elif topic == "payment":
        info = "We accept UPI, debit and credit cards, and cash. Larger treatment plans can be paid in stages."
    elif topic == "insurance":
        info = ("We provide itemised bills and reports for reimbursement claims. "
                "Cashless insurance is not available at the moment.")
    elif topic == "parking":
        info = "There is limited two-wheeler and car parking in front of the clinic, and street parking on 12th Main."
    elif topic == "policies":
        info = ("You can cancel or reschedule free of charge up to 2 hours before your appointment. "
                "If you're running late, we hold your slot for 15 minutes. Children must be accompanied by a parent or guardian.")
    elif topic == "first_visit":
        info = ("Please arrive 10 minutes early and bring any previous dental X-rays or prescriptions. "
                "The first visit includes an examination and a treatment plan. An X-ray is taken only if the dentist advises it.")
    else:  # overview
        info = (f"{CLINIC['name']} is a family and cosmetic dental clinic in Indiranagar, Bengaluru, with three dentists "
                "covering general dentistry, root canals and implants, and orthodontics.")
    return {"ok": True, "topic": topic, "info": info,
            "say": "Answer using only this information, in one or two short spoken sentences."}


# ----scheduling store
_LOCK = threading.RLock()
_BOOKINGS: dict[str, dict] = {}
_TAKEN: set[tuple[str, str, str]] = set()
_CALLBACKS: list[dict] = []


def now_ist() -> datetime:
    return datetime.now(IST)


def fmt_time(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def fmt_date(d: date) -> str:
    return f"{_DAY_NAMES[d.weekday()]}, {d.day} {d.strftime('%B %Y')}"


def _err(code: str, say: str, **extra) -> dict:
    return {"ok": False, "error": code, "say": say, **extra}


def _busy(d: date, doc: str, slot: str) -> bool:
    """Deterministic pseudo-random 'already booked' pattern so the demo calendar looks real."""
    h = hashlib.sha256(f"{d.isoformat()}|{doc}|{slot}".encode()).digest()[0]
    return h % 100 < 35


def _slot_dt(d: date, slot: str) -> datetime:
    h, m = (int(x) for x in slot.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def _free_slots(d: date, doc: str) -> list[str]:
    if d.weekday() not in DOCTORS[doc]["days"]:
        return []
    now = now_ist()
    out = []
    for s in SLOT_TIMES:
        if (d.isoformat(), doc, s) in _TAKEN or _busy(d, doc, s):
            continue
        if _slot_dt(d, s) < now + timedelta(minutes=60):
            continue
        out.append(s)
    return out


def _check_date(d: date) -> Optional[dict]:
    today = now_ist().date()
    if d < today:
        return _err("date_in_past", "That date has already passed. Ask for a date from today onwards.")
    if d > today + timedelta(days=60):
        return _err("too_far", "We only book up to 60 days ahead. Suggest an earlier date.")
    if d.weekday() == 6:
        return _err("closed", "The clinic is closed on Sundays. Offer Monday or another day.")
    return None


def _eligible_doctors(svc: str, doctor: Optional[str]) -> tuple[list[str], Optional[dict]]:
    docs = list(SERVICES[svc]["docs"])
    want = resolve_doctor(doctor)
    if doctor and want:
        if want not in docs:
            names = " or ".join(DOCTORS[k]["name"] for k in docs)
            return [], _err("doctor_mismatch", f"{DOCTORS[want]['name']} doesn't handle that treatment. {names} does.")
        docs = [want]
    return docs, None


def _next_open(start: date, svc: str, docs: list[str], limit: int = 3) -> list[dict]:
    out = []
    d = start
    for _ in range(21):
        d += timedelta(days=1)
        if _check_date(d):
            continue
        opts = sorted((s, doc) for doc in docs for s in _free_slots(d, doc))
        if opts:
            s, doc = opts[0]
            out.append({"date": d.isoformat(), "day": fmt_date(d), "time": s, "spoken": fmt_time(s),
                        "doctor": DOCTORS[doc]["name"]})
        if len(out) >= limit:
            break
    return out


def check_availability(date_str: str, treatment: Optional[str] = None, doctor: Optional[str] = None) -> dict:
    d = date.fromisoformat(date_str)
    svc = resolve_service(treatment) or "consultation"
    docs, e = _eligible_doctors(svc, doctor)
    if e:
        return e
    e = _check_date(d)
    if e:
        e["next_available"] = _next_open(max(d, now_ist().date() - timedelta(days=1)), svc, docs) if e["error"] == "closed" else []
        return e
    by_time: dict[str, str] = {}
    for s, doc in sorted((s, doc) for doc in docs for s in _free_slots(d, doc)):
        by_time.setdefault(s, doc)
    times = list(by_time)
    if len(times) > 6:
        step = (len(times) - 1) / 5
        times = [times[round(i * step)] for i in range(6)]
    options = [{"time": t, "spoken": fmt_time(t), "doctor": DOCTORS[by_time[t]]["name"]} for t in times]
    res = {"ok": True, "date": d.isoformat(), "day": fmt_date(d), "treatment": SERVICES[svc]["name"],
           "options": options,
           "say": "Offer two or three of these times, not the whole list."}
    if not options:
        res["next_available"] = _next_open(d, svc, docs)
        res["say"] = "Nothing is free that day. Offer the next available options."
    return res


def validate_booking(a: dict, ignore_booking_id: Optional[str] = None) -> tuple[Optional[dict], Optional[dict]]:
    """Check every rule WITHOUT writing anything. Returns (error, plan)."""
    d = date.fromisoformat(a["date"])
    e = _check_date(d)
    if e:
        return e, None
    if a["time"] not in SLOT_TIMES:
        return _err("invalid_time", "Appointments start on the half hour, 9:30 to 1:00 PM and 2:30 to 7:00 PM. Ask for a valid time."), None
    svc = resolve_service(a.get("treatment")) or "consultation"
    docs, e = _eligible_doctors(svc, a.get("doctor"))
    if e:
        return e, None
    with _LOCK:
        if ignore_booking_id is None:
            active = [b for b in _BOOKINGS.values() if b["phone"] == a["phone"] and b["status"] == "confirmed"
                      and _slot_dt(date.fromisoformat(b["date"]), b["time"]) > now_ist()]
            if len(active) >= 3:
                return _err("too_many_bookings", "This number already has 3 upcoming appointments. Offer to reschedule one instead."), None
            if any(b["date"] == a["date"] for b in active):
                return _err("already_booked_that_day", "This number already has an appointment that day. Offer to reschedule it instead."), None
        pick = next((doc for doc in docs if a["time"] in _free_slots(d, doc)), None)
    if not pick:
        alt = check_availability(a["date"], a.get("treatment"), a.get("doctor"))
        return _err("slot_unavailable", "That time is not available. Offer these alternatives.",
                    options=alt.get("options", []), next_available=alt.get("next_available", [])), None
    return None, {"date": d, "time": a["time"], "doctor_id": pick, "service": svc}


def readback(a: dict, plan: dict) -> str:
    return (f"{a['patient_name']}, {SERVICES[plan['service']]['name']} with {DOCTORS[plan['doctor_id']]['name']} "
            f"on {fmt_date(plan['date'])} at {fmt_time(plan['time'])}. Phone number ending {a['phone'][-4:]}.")


def _new_id() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    while True:
        bid = "SC-" + "".join(secrets.choice(alphabet) for _ in range(4))
        if bid not in _BOOKINGS:
            return bid


def create_booking(a: dict, plan: dict) -> dict:
    with _LOCK:
        key = (plan["date"].isoformat(), plan["doctor_id"], plan["time"])
        if plan["time"] not in _free_slots(plan["date"], plan["doctor_id"]):
            return _err("slot_unavailable", "Someone just took that slot. Offer another time.")
        bid = _new_id()
        _BOOKINGS[bid] = {"id": bid, "name": a["patient_name"], "phone": a["phone"], "date": plan["date"].isoformat(),
                          "time": plan["time"], "doctor_id": plan["doctor_id"], "service": plan["service"],
                          "new_patient": a.get("is_new_patient", True), "status": "confirmed"}
        _TAKEN.add(key)
    return {"ok": True, "booking_id": bid, "summary": readback(a, plan),
            "say": ("Confirm the booking, read the booking ID slowly character by character, mention arriving 10 minutes early, "
                    "and say that this demo does not send an SMS.")}


def _public(b: dict) -> dict:
    return {"booking_id": b["id"], "day": fmt_date(date.fromisoformat(b["date"])), "date": b["date"],
            "time": b["time"], "spoken": fmt_time(b["time"]), "doctor": DOCTORS[b["doctor_id"]]["name"],
            "treatment": SERVICES[b["service"]]["name"]}


_VERIFY_FAIL = _err("verification_failed",
                    "Say you couldn't find a booking with those details. Ask the caller to recheck the booking ID and phone number. "
                    "Never say which detail was wrong.")


def _find(booking_id: str, phone: str) -> Optional[dict]:
    b = _BOOKINGS.get((booking_id or "").upper().strip())
    if b and b["phone"] == phone and b["status"] == "confirmed":
        return b
    return None


def lookup_appointments(phone: str, patient_name: str) -> dict:
    first = patient_name.strip().split()[0].lower()
    with _LOCK:
        mine = [b for b in _BOOKINGS.values() if b["phone"] == phone and b["status"] == "confirmed"
                and b["name"].split()[0].lower() == first
                and _slot_dt(date.fromisoformat(b["date"]), b["time"]) > now_ist()]
    if not mine:
        return dict(_VERIFY_FAIL)
    return {"ok": True, "appointments": [_public(b) for b in sorted(mine, key=lambda x: (x["date"], x["time"]))],
            "say": "Read out the upcoming appointment(s) briefly."}


def _within_policy(b: dict) -> bool:
    return _slot_dt(date.fromisoformat(b["date"]), b["time"]) - now_ist() >= timedelta(hours=2)


def cancel_appointment(booking_id: str, phone: str) -> dict:
    with _LOCK:
        b = _find(booking_id, phone)
        if not b:
            return dict(_VERIFY_FAIL)
        if not _within_policy(b):
            return _err("too_late", "It is within 2 hours of the appointment, so it can't be cancelled by phone. "
                                    "Offer to connect the caller with the front desk.")
        b["status"] = "cancelled"
        _TAKEN.discard((b["date"], b["doctor_id"], b["time"]))
    return {"ok": True, "cancelled": _public(b), "say": "Confirm the cancellation and offer to rebook."}


def reschedule_appointment(booking_id: str, phone: str, new_date: str, new_time: str) -> dict:
    with _LOCK:
        b = _find(booking_id, phone)
        if not b:
            return dict(_VERIFY_FAIL)
        if not _within_policy(b):
            return _err("too_late", "It is within 2 hours of the appointment, so it can't be changed by phone. "
                                    "Offer to connect the caller with the front desk.")
        a = {"date": new_date, "time": new_time, "phone": phone, "treatment": b["service"],
             "doctor": DOCTORS[b["doctor_id"]]["name"]}
        err, plan = validate_booking(a, ignore_booking_id=b["id"])
        if err and err["error"] == "slot_unavailable":
            a["doctor"] = None
            err, plan = validate_booking(a, ignore_booking_id=b["id"])
        if err:
            return err
        _TAKEN.discard((b["date"], b["doctor_id"], b["time"]))
        b.update(date=plan["date"].isoformat(), time=plan["time"], doctor_id=plan["doctor_id"])
        _TAKEN.add((b["date"], b["doctor_id"], b["time"]))
    return {"ok": True, "updated": _public(b), "say": "Confirm the new date, time and doctor."}


def request_callback(reason: str, callback_phone: Optional[str]) -> dict:
    with _LOCK:
        _CALLBACKS.append({"reason": reason, "phone": callback_phone, "at": now_ist().isoformat()})
    return {"ok": True,
            "say": "Tell the caller the front desk will call back during working hours (Monday to Saturday, 9:30 AM to 7:30 PM)."}


_RED_FLAGS = re.compile(
    r"breath|swallow|bleed(ing)? (a lot|heavily|won'?t|will not|for)|heavy bleeding|uncontrol|"
    r"swell\w* (in|around|under|near).{0,15}(eye|neck|throat)|(eye|neck|throat).{0,15}swell|"
    r"face.{0,12}swoll|swollen face|head injur|hit (my|his|her) head|unconscious|faint|fever|accident|jaw.{0,10}(broken|fracture)",
    re.I)
_KNOCKED = re.compile(r"knock|fell out|came out|avuls", re.I)


def emergency_guidance(symptoms: str) -> dict:
    if _RED_FLAGS.search(symptoms or ""):
        return {"ok": True, "severity": "severe",
                "say": ("Speak calmly and clearly: this could be serious and needs urgent medical care. Ask them to go to the nearest "
                        "hospital emergency department right now, or call 108 for an ambulance or 112 for emergency services. "
                        "Do not make them wait for a clinic appointment. Do not ask further questions.")}
    today = now_ist().date()
    svc = "emergency"
    docs = ALL_DOCS
    options = []
    if not _check_date(today):
        options = sorted((s, doc) for doc in docs for s in _free_slots(today, doc))[:2]
        options = [{"date": today.isoformat(), "time": s, "spoken": fmt_time(s), "doctor": DOCTORS[doc]["name"]} for s, doc in options]
    res = {"ok": True, "severity": "urgent_not_life_threatening", "today_options": options,
           "next_available": [] if options else _next_open(today, svc, docs),
           "say": ("Express empathy briefly. Do not diagnose or suggest any medicine. Offer the earliest slot below and use "
                   "book_appointment with treatment 'emergency'. Remind them to go to a hospital emergency department if "
                   "swelling spreads, they have fever, or they have trouble breathing or swallowing.")}
    if _KNOCKED.search(symptoms or ""):
        res["first_aid"] = ("For a knocked-out adult tooth: hold it by the crown, not the root, do not scrub it, keep it in milk, "
                            "and come to the clinic immediately.")
    return res
