import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import threading
import time

class FirestoreManager:
    def __init__(self, key_path="serviceAccountKey.json"):
        try:
            # Check if app is already initialized
            if not firebase_admin._apps:
                cred = credentials.Certificate(key_path)
                firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            self.connected = True
            print("Firebase connected successfully.")
        except Exception as e:
            self.connected = False
            print(f"Failed to connect to Firebase: {e}")

        self.collection_name = "sleep_monitor"
        self.doc_id = "current_state"

    def update_state(self, data):
        """Update the real-time state document."""
        if not self.connected:
            return False
            
        data["last_updated"] = firestore.SERVER_TIMESTAMP
        try:
            doc_ref = self.db.collection(self.collection_name).document(self.doc_id)
            doc_ref.set(data, merge=True)
            return True
        except Exception as e:
            print(f"Error updating state: {e}")
            return False

    def log_history(self, data):
        """Save a historical record of the state."""
        if not self.connected:
            return False
            
        data["timestamp"] = firestore.SERVER_TIMESTAMP
        try:
            self.db.collection(self.collection_name).document(self.doc_id).collection("history").add(data)
            return True
        except Exception as e:
            print(f"Error logging history: {e}")
            return False

class FirebaseSyncThread(threading.Thread):
    def __init__(self, firestore_manager, hardware, vision, sync_interval=5):
        super().__init__(daemon=True)
        self.db = firestore_manager
        self.hardware = hardware
        self.vision = vision
        self.sync_interval = sync_interval
        self.running = True
        self.is_awake = False

    def set_awake_status(self, status):
        self.is_awake = status

    def run(self):
        while self.running:
            # Gather current data
            data = {
                "temperature": self.hardware.get_temperature(),
                "humidity": self.hardware.get_humidity(),
                "light_lux": self.hardware.get_light(),
                "actuators": {
                    "fan_on": self.hardware.fan_on,
                    "humidifier_on": self.hardware.humidifier_on,
                    "led_on": self.hardware.led_on
                },
                "status": "awake" if self.is_awake else "asleep"
            }
            
            # Push to Firebase
            self.db.update_state(data)
            
            # Wait for next sync
            for _ in range(self.sync_interval):
                if not self.running:
                    break
                time.sleep(1)

    def stop(self):
        self.running = False
