import requests
import time
import pandas as pd
from datetime import datetime, timezone
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- API and Authentication Configuration ---
API_BASE_URL = "http://localhost:8000"
API_USERNAME = "user123"
API_PASSWORD = "securepassword"

# --- Data File Paths ---
HEARTRATE_FILE = "heartrate_seconds_merged.csv"
CALORIES_FILE = "minuteCaloriesNarrow_merged.csv"
STEPS_FILE = "minuteStepsNarrow_merged.csv"


def get_access_token(session: requests.Session) -> str:
    """
    Authenticates with the API and returns a JWT access token.
    """
    try:
        response = session.post(
            f"{API_BASE_URL}/token",
            data={"username": API_USERNAME, "password": API_PASSWORD},
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data["access_token"]
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get access token: {e}")
        return None


def send_data_to_api(
    session: requests.Session, endpoint: str, data: dict, token: str
) -> bool:
    """
    Sends data to a specific API endpoint using a JWT token.
    Returns True on success, False otherwise.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = session.post(f"{API_BASE_URL}{endpoint}", json=data, headers=headers)
        response.raise_for_status()
        logging.info(f"Successfully sent data to {endpoint}: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to send data to {endpoint}: {e}")
        return False


def simulate_realtime_stream():
    """
    Simulates a real-time data stream by reading from CSVs and
    sending data to the API at different intervals.
    """
    logging.info("Loading data from CSV files...")
    try:
        hr_df = pd.read_csv(HEARTRATE_FILE)
        cal_df = pd.read_csv(CALORIES_FILE)
        steps_df = pd.read_csv(STEPS_FILE)
    except FileNotFoundError as e:
        logging.error(f"Error: A required file was not found: {e.filename}")
        return

    # Process and sort dataframes
    hr_df.rename(
        columns={"Id": "user_id", "Time": "time", "Value": "heart_rate"}, inplace=True
    )
    cal_df.rename(
        columns={"Id": "user_id", "ActivityMinute": "time", "Calories": "calories"},
        inplace=True,
    )
    steps_df.rename(
        columns={"Id": "user_id", "ActivityMinute": "time", "Steps": "steps"},
        inplace=True,
    )

    # Convert timestamps and ensure they are timezone-aware for API
    for df in [hr_df, cal_df, steps_df]:
        df["time"] = pd.to_datetime(df["time"], format="%m/%d/%Y %I:%M:%S %p")
        df["time"] = df["time"].dt.tz_localize("UTC")
        df.sort_values(by="time", inplace=True)

    # Indexes to keep track of the current position in each dataframe
    hr_idx, cal_idx, steps_idx = 0, 0, 0
    total_hr_rows = len(hr_df)
    total_cal_rows = len(cal_df)
    total_steps_rows = len(steps_df)

    # Use a requests Session for connection pooling and authentication
    with requests.Session() as session:
        # Get initial token
        token = get_access_token(session)
        if not token:
            logging.error("Authentication failed. Exiting simulation.")
            return

        logging.info("Starting real-time simulation... Press Ctrl+C to stop.")

        last_hr_time = datetime.now()
        last_minute_data_time = datetime.now().replace(second=0, microsecond=0)

        while True:
            try:
                current_time = datetime.now()

                # Check if it's time to send heart rate data (every second)
                if (
                    current_time - last_hr_time
                ).total_seconds() >= 1 and hr_idx < total_hr_rows:
                    row = hr_df.iloc[hr_idx]
                    data = {
                        "user_id": str(row["user_id"]),
                        "time": datetime.now(
                            timezone.utc
                        ).isoformat(),  # <-- updated line
                        "heart_rate": int(row["heart_rate"]),
                    }
                    send_data_to_api(session, "/ingest/heartrate", data, token)
                    hr_idx += 1
                    last_hr_time = current_time

                if (current_time - last_minute_data_time).total_seconds() >= 60:
                    if cal_idx < total_cal_rows:
                        cal_row = cal_df.iloc[cal_idx]
                        data = {
                            "user_id": str(cal_row["user_id"]),
                            "time": datetime.now(
                                timezone.utc
                            ).isoformat(),  # <-- updated line
                            "calories": float(cal_row["calories"]),
                        }
                        send_data_to_api(session, "/ingest/calories", data, token)
                        cal_idx += 1

                    if steps_idx < total_steps_rows:
                        steps_row = steps_df.iloc[steps_idx]
                        data = {
                            "user_id": str(steps_row["user_id"]),
                            "time": datetime.now(
                                timezone.utc
                            ).isoformat(),  # <-- updated line
                            "steps": int(steps_row["steps"]),
                        }
                        send_data_to_api(session, "/ingest/steps", data, token)
                        steps_idx += 1

                    last_minute_data_time = current_time.replace(
                        second=0, microsecond=0
                    )

                # Exit if all data has been ingested
                if (
                    hr_idx >= total_hr_rows
                    and cal_idx >= total_cal_rows
                    and steps_idx >= total_steps_rows
                ):
                    logging.info(
                        "\nAll data has been successfully streamed and ingested."
                    )
                    break

                time.sleep(0.1)  # Small sleep to prevent busy-waiting

            except KeyboardInterrupt:
                logging.info("\nSimulation stopped by user.")
                break
            except Exception as e:
                logging.error(f"An unexpected error occurred: {e}")
                break


if __name__ == "__main__":
    simulate_realtime_stream()
