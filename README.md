# Django SMS Sender

**IT 120 – Integrative Programming and Technologies · Group Assignment (1st Sem SY 2026-27)**

A Django web application that sends SMS messages through [Twilio](https://www.twilio.com/). The user types a
recipient number and a message; the app validates both, submits the message to Twilio, records the attempt, and
shows an honest success or error message. It also tracks each message's status, so *"the provider accepted it"*
is never confused with *"it was delivered"*.

## Group members and responsibilities

> Fill in your real names before submitting. Roles are the suggested split from the assignment sheet.

| Member | Responsibility |
|---|---|
| Member 1 – _Name_ | Django project setup, URLs, views, application logic (`sms_project/`, `sms_app/views.py`, `urls.py`, `models.py`) |
| Member 2 – _Name_ | User interface, forms, validation, user feedback (`templates/`, `static/`, `forms.py`, `validators.py`) |
| Member 3 – _Name_ | Twilio integration, testing, documentation, demo video (`services.py`, `tests.py`, `README.md`, `docs/`) |

## Main features

**Required**
- SMS compose form: recipient number, message, *Send SMS* button.
- Input validation before anything is sent (empty / malformed number, empty / over-long message).
- Twilio integration with safe, human-readable error handling (missing or wrong credentials, network errors and
  timeouts, rejected numbers, unverified trial recipients).
- Success / failure feedback on every attempt.
- CSRF protection on every form; credentials only in environment variables.

**Additional**
- **Message history dashboard** – every attempt with time, recipient, text, status and totals.
- **Message status tracking** – *Refresh status* asks Twilio for the latest status
  (`queued → sent → delivered / undelivered / failed`). The app only says "Delivered" when Twilio confirms it.
- **Live character counter, SMS-segment estimate and message preview** while typing.
- **Contact management** – save, pick and delete recipients.
- Local numbers are converted automatically (`09171234567` → `+639171234567`, configurable country code).

## Technologies

Python 3.10+, Django 4.2 – 5.x, Twilio Python SDK 9.x, SQLite, HTML/CSS/vanilla JavaScript (no CDN, works offline).
Dependencies are listed in `requirements.txt`.

## How it works

```
Browser ──POST──▶ send_sms view ──▶ SendSMSForm (validators.py)
                                      │ valid
                                      ▼
                          get_backend().send()  (services.py)
                          ├─ TwilioBackend ──▶ Twilio REST API
                          └─ SimulatedBackend (SMS_BACKEND=console, nothing is sent)
                                      │
              SMSMessage saved ◀──────┘  (status + provider SID, or the error)
                                      ▼
                        flash message ──▶ redirect / re-render form
```

- `sms_app/validators.py` – phone normalisation to E.164 and message checks.
- `sms_app/services.py` – provider layer. Every failure becomes an `SMSError` subclass with a message that is safe to
  show (never credentials or stack traces).
- `sms_app/views.py` – send, history, status refresh, contacts.
- `sms_app/tests.py` – automated tests; the provider is always mocked, so **no real SMS is sent by the tests**.

## Installation and setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your private configuration file
copy .env.example .env         # Windows   (cp .env.example .env on macOS/Linux)
# then edit .env and fill in the values (see below)

# 4. Create the database
python manage.py migrate
```

### Configuring Twilio

1. Create an account at <https://www.twilio.com/try-twilio>.
2. In the Twilio Console copy your **Account SID** and **Auth Token** into `.env`
   (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`).
3. Get a Twilio phone number (or a Messaging Service) and put it in `TWILIO_PHONE_NUMBER`
   (or `TWILIO_MESSAGING_SERVICE_SID`).
4. **Trial accounts** can only text numbers you have verified: Console → *Phone Numbers → Verified Caller IDs*.
   Trial messages also start with "Sent from your Twilio trial account".
5. Set `DEFAULT_COUNTRY_CODE` if you are not in the Philippines (default `63`).

> **Security:** `.env` is git-ignored. Never commit it, and never show it (or the Twilio Console token page) in the
> demo video. Only `.env.example`, which holds placeholders, is in the repository.

Want to try the interface before you have Twilio credentials? Set `SMS_BACKEND=console`. The app then **simulates**
sending (nothing leaves your computer) and shows a yellow "Simulation mode" banner. Use `twilio` for the real demo.

## Running the application

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Testing

Automated tests (no real SMS, no credentials needed):

```bash
python manage.py test
```

Manual test cases (run with `SMS_BACKEND=twilio` and an **authorized, verified** test recipient, then fill in the
Result column before submitting):

| # | Test case | Expected result | Result |
|---|---|---|---|
| 1 | Valid number and message | Message accepted; green notice that says delivery is *not* yet confirmed; row appears in History | |
| 2 | Empty phone number | "Please enter a recipient phone number."; nothing sent | |
| 3 | Empty message | "Please type a message before sending."; nothing sent | |
| 4 | Invalid number (`abc`, `+6391`) | Validation error under the field; nothing sent | |
| 5 | Wrong / missing credentials (edit `.env`, restart) | Red notice about configuration; no secrets shown | |
| 6 | Network disconnected | "Could not reach the SMS provider…" | |
| 7 | Unverified trial recipient | Provider rejection explained; attempt saved as *Failed* | |
| 8 | Refresh status after a few seconds | Status moves from *Queued/Sent* to *Delivered* only when Twilio confirms | |

## Known limitations

- The app has **no login**: anyone who can open the page can send SMS using your Twilio account. Run it locally only;
  add authentication before deploying it anywhere public.
- Delivery status is fetched on demand (*Refresh status*). Real-time updates would need a public Twilio status
  webhook, which is outside the scope of this assignment.
- Twilio trial accounts only reach verified numbers and prefix every message.
- The SMS segment counter is an estimate (ASCII = GSM-7, everything else = UCS-2).
- SQLite is used for simplicity.

## Repository layout

```
manage.py
requirements.txt
.env.example            # placeholders only - copy to .env
sms_project/            # settings, root URLs, WSGI/ASGI
sms_app/                # models, forms, validators, services (Twilio), views, templates, static, tests
docs/                   # demo-video script and submission checklist
```
