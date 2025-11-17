import json
import logging
from kafka import KafkaConsumer, KafkaProducer
from fastapi import FastAPI, WebSocket
from threading import Thread
import uvicorn

# Logging config
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Kafka config
KAFKA_BROKER = "localhost:9092"
CONSUME_TOPICS = ["heartrate", "steps"]
ALERT_TOPIC = "alerts"

# ----- FastAPI App -----
app = FastAPI(title="Notification Engine (Realtime)")

# WebSocket clients connectés
websocket_clients = []

# ----- Consumer Kafka -----
def consume_and_analyze():
    consumer = KafkaConsumer(
        *CONSUME_TOPICS,
        bootstrap_servers=KAFKA_BROKER,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        group_id="notification_engine",
        enable_auto_commit=True,
        auto_offset_reset="latest"
    )

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode("utf-8")
    )

    logging.info("Notification Engine started... Listening for anomalies.")

    for record in consumer:
        topic = record.topic
        data = record.value
        alert = None

        if topic == "heartrate":
            hr = data.get("heart_rate", 0)
            if hr < 50:
                alert = f"⚠️ Low heart rate detected ({hr} bpm)"
            elif hr > 120:
                alert = f"⚠️ High heart rate detected ({hr} bpm)"

        elif topic == "steps":
            steps = data.get("steps", 0)
            if steps < 500:
                alert = f"⚠️ Very low activity ({steps} steps)"
            elif steps > 10000:
                alert = f"⚠️ Very high activity ({steps} steps) → consider a break"

        if alert:
            alert_event = {
                "user_id": data.get("user_id"),
                "time": data.get("time"),
                "alert": alert
            }
            logging.warning(f"ALERT GENERATED: {alert_event}")

            # Envoi dans le topic Kafka "alerts"
            producer.send(ALERT_TOPIC, alert_event)

            # Envoi en temps réel aux WebSocket connectés
            for ws in websocket_clients:
                try:
                    import asyncio
                    asyncio.run(ws.send_json(alert_event))
                except Exception as e:
                    logging.error(f"WebSocket send failed: {e}")


# ----- WebSocket Endpoint -----
@app.websocket("/ws/alerts")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.append(websocket)
    logging.info("New WebSocket client connected.")
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except Exception:
        logging.warning("WebSocket client disconnected.")
    finally:
        websocket_clients.remove(websocket)


# ----- Start Consumer in Background -----
Thread(target=consume_and_analyze, daemon=True).start()

# ----- Run FastAPI -----
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
