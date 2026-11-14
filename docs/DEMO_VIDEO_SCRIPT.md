# Demo video script (target: 5–7 minutes; allowed: 3–10)

**Before recording:** `.env` values are correct, the server is running, the Android phone with the TextBee app is online, and
you are *not* showing `.env`, the TextBee API-key page, or any password. Hide bookmarks/notifications. Close the editor tab
that holds `.env`. Check the final video length is between 3 and 10 minutes.

| Time | Who | Show / say |
|---|---|---|
| 0:00 | Member 1 | Introduce the project and group; purpose: send SMS through TextBee (an Android phone gateway) from a Django web app. |
| 0:30 | Member 1 | Project structure in the editor (`sms_project`, `sms_app`, `services.py`, `.env.example`, `.gitignore`). Mention credentials live in `.env`, which is not in GitHub. |
| 1:15 | Member 2 | Open the app: the Send SMS page. Point out the form, live character counter, segment estimate and message preview. |
| 2:00 | Member 2 | **Validation tests:** submit with empty number, empty message, and an invalid number (`abc`). Show the error messages. |
| 3:00 | Member 3 | **Successful send** to your authorized test recipient. Show the green notice — it says *accepted*, not *delivered*. Show the phone receiving the SMS. |
| 4:00 | Member 3 | **History** page: the new row, statistics, then **Refresh status** (Queued/Sent → Delivered). |
| 4:45 | Member 2 | **Contacts:** add a contact, pick it on the Send page. |
| 5:15 | Member 3 | **Error handling:** show one provider/credential failure (e.g. temporarily blank `TEXTBEE_API_KEY` in `.env` off-camera, restart, send) → friendly message with no secrets. Restore it afterwards. |
| 5:45 | Member 3 | Run `python manage.py test` and show it passing. |
| 6:15 | All | Technologies (Python, Django, TextBee REST API via `requests`, SQLite, HTML/CSS/JS), security (env vars, CSRF, `.gitignore`), and what each member contributed. |

Tip: every member should be able to explain the workflow — form → validation → provider → saved record → feedback.
