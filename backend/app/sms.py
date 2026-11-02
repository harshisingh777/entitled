"""SMS through the Twilio sandbox when configured. Otherwise the message stays in-app, marked simulated."""
from . import config


def send_sms(mobile: str | None, body: str) -> str:
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN and config.TWILIO_FROM and mobile):
        return "simulated"
    try:
        from twilio.rest import Client
        Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN).messages.create(
            to=f"+91{mobile[-10:]}", from_=config.TWILIO_FROM, body=body)
        return "sms"
    except Exception:  # A failed reminder must not break the status poll. It is still visible in-app.
        return "sms_failed"
