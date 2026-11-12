# Amazon India Dashboard — connected frontend + backend

## Run locally

1. Install Python 3.10+ (Python 3.12 is supported).
2. Create and activate a virtual environment.
3. Install dependencies: `pip install -r requirements.txt` (includes `python-dotenv`).
4. Ensure the configuration file is named exactly `.env` in the same folder as `app.py`. The project includes a local `.env` file; do not publish it or share its contents. If it is missing, copy `.env.example` to `.env` and enter your Google Web Client ID.
5. Run: `python app.py`.
6. Open `http://127.0.0.1:5001`.
7. Choose **Create account**, register with an email and a password of at least 6 characters, then sign in.

## How it is connected

- Flask serves `static/index.html` and the `/api/*` endpoints on the same origin.
- The frontend requests `/api/me` to restore the server-side login session.
- After authentication, the frontend requests `/api/data`; the charts, filters, search, and drill-downs use that API response.
- `/api/summary` and `/api/breakdown` expose server-calculated metrics and filtered breakdowns.
- SQLite stores user accounts; passwords are hashed with Werkzeug.
- Sign-out clears the server session.

## Google sign-in (optional)

Set `GOOGLE_CLIENT_ID` to a Google OAuth 2.0 Web client ID and add the exact app origin (for local use, `http://localhost:5001` and/or `http://127.0.0.1:5001`) to the Authorized JavaScript origins in Google Cloud Console. Restart Flask. Google sign-in remains unavailable until this is configured.

## Data source note

The uploaded ZIP contained only `app.py` and `requirements.txt`; it did not contain the original Excel workbook. To make the supplied project runnable, `data/Amazon_Sales_Data_India.xlsx` was reconstructed from the dashboard's existing embedded data array in the supplied HTML. If you have the original workbook, replace this generated workbook with it (keep the required column names) or set `DATA_FILE` to its path.

## Deployment

Set a strong `SECRET_KEY`, set `COOKIE_SECURE=1` behind HTTPS, and run with a production WSGI server, for example: `gunicorn -w 2 -b 0.0.0.0:5001 app:app`. Do not use Flask debug mode in production.
