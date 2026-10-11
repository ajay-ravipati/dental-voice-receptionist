"""Function declarations that Gemini Live sees. Validation happens again server-side in schemas.py."""
from google.genai import types


def _s(desc: str, enum: list[str] | None = None) -> types.Schema:
    return types.Schema(type="STRING", description=desc, enum=enum)


def _b(desc: str) -> types.Schema:
    return types.Schema(type="BOOLEAN", description=desc)


def _decl(name: str, desc: str, props: dict, required: list[str]) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=name, description=desc,
        parameters=types.Schema(type="OBJECT", properties=props, required=required))


PHONE = "10-digit Indian mobile number, digits only, as confirmed by the caller"
DATE = "Date as YYYY-MM-DD. Work this out from today's date given in your instructions."
TIME = "24-hour time HH:MM, for example 15:30 for 3:30 PM"

FUNCTION_DECLARATIONS = [
    _decl("get_clinic_info",
          "Look up factual information about the clinic. ALWAYS use this for questions about hours, address, doctors, "
          "prices, payment, insurance, parking, policies or first-visit instructions. Never answer these from memory.",
          {"topic": _s("What the caller wants to know",
                       ["overview", "hours", "location", "services", "pricing", "doctors", "payment",
                        "insurance", "parking", "policies", "first_visit", "contact"]),
           "service": _s("For topic=pricing: the treatment the caller asked about, e.g. 'root canal'")},
          ["topic"]),
    _decl("check_availability",
          "Find free appointment times on a given date. Call this before offering any time to the caller.",
          {"date": _s(DATE),
           "treatment": _s("Treatment or reason for the visit, e.g. 'check-up', 'root canal', 'braces'"),
           "doctor": _s("Preferred doctor's name, only if the caller asked for one")},
          ["date"]),
    _decl("book_appointment",
          "Book an appointment. Call it FIRST with caller_confirmed=false to get a read-back summary, read that summary to the "
          "caller, and only after they clearly say yes call it again with identical details and caller_confirmed=true.",
          {"patient_name": _s("Caller's full name, spelling confirmed"),
           "phone": _s(PHONE), "date": _s(DATE), "time": _s(TIME),
           "treatment": _s("Treatment or reason for the visit"),
           "is_new_patient": _b("True if this is the caller's first visit"),
           "caller_confirmed": _b("True only after the caller said yes to the read-back"),
           "doctor": _s("Preferred doctor, only if requested")},
          ["patient_name", "phone", "date", "time", "treatment", "caller_confirmed"]),
    _decl("lookup_appointments",
          "Find a caller's upcoming appointments. Needs both phone number and the first name used when booking.",
          {"phone": _s(PHONE), "patient_name": _s("Name used when booking")},
          ["phone", "patient_name"]),
    _decl("cancel_appointment",
          "Cancel an appointment. Needs the booking ID and the phone number it was booked with. Confirm with the caller first.",
          {"booking_id": _s("Booking ID such as SC-7K2P"), "phone": _s(PHONE)},
          ["booking_id", "phone"]),
    _decl("reschedule_appointment",
          "Move an appointment to a new date and time. Check availability first. Needs booking ID and phone.",
          {"booking_id": _s("Booking ID such as SC-7K2P"), "phone": _s(PHONE),
           "new_date": _s(DATE), "new_time": _s(TIME)},
          ["booking_id", "phone", "new_date", "new_time"]),
    _decl("request_callback",
          "Ask the human front desk to call the caller back. Use for complaints, billing disputes, medical-record requests, "
          "anything you cannot handle, or when the caller asks for a human.",
          {"reason": _s("Short reason for the callback"), "callback_phone": _s(PHONE)},
          ["reason"]),
    _decl("flag_dental_emergency",
          "Call whenever the caller describes severe pain, swelling, bleeding, a knocked-out or broken tooth, or any injury.",
          {"symptoms": _s("What the caller described, in a few words")},
          ["symptoms"]),
]
