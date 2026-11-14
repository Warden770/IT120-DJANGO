# Django SMS Sender

**IT 120 – Integrative Programming and Technologies · Group Assignment (1st Sem SY 2026-27)**

A Django web application that sends SMS messages through [TextBee](https://textbee.dev/), an open-source gateway
that turns an Android phone into an SMS API. The user types a recipient number and a message; the app validates
both, submits the message to TextBee (which makes the phone send it from its own SIM), records the attempt, and
shows an honest success or error message. It also tracks each message's status, so *"the provider accepted it"*
is never confused with *"it was delivered"*.

## Group members and responsibilities

> Fill in your real names before submitting. Roles are the suggested split from the assignment sheet.

| Member | Responsibility |
|---|---|
| Member 1 – _Name_ | Django project setup, URLs, views, application logic (`sms_project/`, `sms_app/views.py`, `urls.py`, `models.py`) |
| Member 2 – _Name_ | User interface, forms, validation, user feedback (`templates/`, `static/`, `forms.py`, `validators.py`) |
| Member 3 – _Name_ | TextBee integration, testing, documentation, demo video (`services.py`, `tests.py`, `README.md`, `docs/`) |

## Main features

**Required**
- SMS compose form: recipient number, message, *Send SMS* button.
- Input validation before anything is sent (empty / malformed number, empty / over-long message).
- TextBee integration with safe, human-readable error handling (missing or wrong API key, no enabled phone,
  network errors and timeouts, rejected numbers, plan limits).
- Success / failure feedback on every attempt.
- CSRF protection on every form; credentials only in environment variables.

**Additional**
- **Message history dashboard** – every attempt with time, recipient, text, status and totals.
- **Message status tracking** – *Refresh status* asks TextBee for the latest status
  (`queued → sending → sent → delivered / failed`). The app only says "Delivered" when the carrier's delivery
  report reaches TextBee (carriers do not always send one).
- **Live character counter, SMS-segment estimate and message preview** while typing.
- **Contact management** – save, pick and delete recipients.
- Local numbers are converted automatically (`09171234567` → `+639171234567`, configurable country code).

## Technologies

Python 3.10+, Django 4.2 – 5.x, `requests`, SQLite, HTML/CSS/vanilla JavaScript (no CDN, works offline).
Dependencies are listed in `requirements.txt`.

## How it works

```
Browser ──POST──▶ send_sms view ──▶ SendSMSForm (validators.py)
                                      │ valid
                                      ▼
                          get_backend().send()  (services.py)
                          ├─ TextBeeBackend ──▶ TextBee REST API ──▶ your Android phone ──▶ SMS
                          └─ SimulatedBackend (SMS_BACKEND=console, nothing is sent)
                                      │
              SMSMessage saved ◀──────┘  (status + TextBee batch id, or the error)
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

### Configuring TextBee

TextBee sends the SMS **from an Android phone you own** (using that phone's SIM card and load), so you need an
Android phone with a SIM and internet access.

1. Create an account at <https://textbee.dev> and verify your email (sending fails until it is verified).
2. On the Android phone, download and install the TextBee APK from <https://textbee.dev/download>
   (allow "install unknown apps"; it is not on the Play Store).
3. In the app tap *Get Started*, scan the QR code shown in the dashboard (or enter an API key manually) and register
   the phone. Allow the **Send SMS** permission and keep the app running.
4. In the dashboard open *API Keys → Generate API Key* and copy the key (it is shown only once) into `.env` as
   `TEXTBEE_API_KEY`.
5. Optional: if you registered more than one phone, set `TEXTBEE_DEVICE_ID` to the one that should send
   (dashboard → Devices). Leave it empty to use your default phone.
6. Set `DEFAULT_COUNTRY_CODE` if you are not in the Philippines (default `63`).

> **Security:** `.env` is git-ignored. Never commit it, and never show it (or the TextBee API-key page) in the
> demo video. Only `.env.example`, which holds placeholders, is in the repository.

Want to try the interface before you have TextBee set up? Set `SMS_BACKEND=console`. The app then **simulates**
sending (nothing leaves your computer) and shows a yellow "Simulation mode" banner. Use `textbee` for the real demo.

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

Manual test cases (run with `SMS_BACKEND=textbee`, the phone online, and an **authorized** test recipient such as
your own number, then fill in the Result column before submitting):

| # | Test case | Expected result | Result |
|---|---|---|---|
| 1 | Valid number and message | Message accepted; green notice that says delivery is *not* yet confirmed; row appears in History | |
| 2 | Empty phone number | "Please enter a recipient phone number."; nothing sent | |
| 3 | Empty message | "Please type a message before sending."; nothing sent | |
| 4 | Invalid number (`abc`, `+6391`) | Validation error under the field; nothing sent | |
| 5 | Wrong / missing API key (edit `.env`, restart) | Red notice about `TEXTBEE_API_KEY`; the key is never shown | |
| 6 | Network disconnected | "Could not reach TextBee…" | |
| 7 | Device disabled in the TextBee dashboard | "TextBee has no enabled phone…" explained; attempt saved as *Failed* | |
| 8 | Refresh status after a few seconds | Status moves from *Queued/Sent* to *Delivered* only when the carrier confirms | |

## Known limitations

- The app has **no login**: anyone who can open the page can send SMS using your TextBee account and your phone's SMS load. Run it locally only;
  add authentication before deploying it anywhere public.
- Delivery status is fetched on demand (*Refresh status*). Real-time updates would need a public TextBee
  webhook, which is outside the scope of this assignment.
- Messages are sent by your own phone, so it must be on, online and have the TextBee app running, and normal
  carrier SMS rates/load apply. TextBee's free plan has daily/monthly message limits.
- "Delivered" depends on the carrier sending a delivery report; some never do, so a message can stay at *Sent*.
- The SMS segment counter is an estimate (ASCII = GSM-7, everything else = UCS-2).
- SQLite is used for simplicity.

## Repository layout

```
manage.py
requirements.txt
.env.example            # placeholders only - copy to .env
sms_project/            # settings, root URLs, WSGI/ASGI
sms_app/                # models, forms, validators, services (TextBee), views, templates, static, tests
docs/                   # demo-video script and submission checklist
```
