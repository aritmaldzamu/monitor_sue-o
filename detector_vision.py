import cv2
import time
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

class VisionDetector(QThread):
    # Signals to communicate with the main GUI
    frame_ready = pyqtSignal(QPixmap)
    status_ready = pyqtSignal(bool) # True for Awake, False for Asleep

    def __init__(self, camera_index=0):
        super().__init__()
        self.camera_index = camera_index
        self.running = True
        # Using Haar cascades for basic face and eye detection
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        
        # Give some time for the camera to warm up
        time.sleep(1)
        if not cap.isOpened():
            self.status_ready.emit(False)
            cap.release()
            return
        
        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
                
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
            
            is_awake = False
            
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 0, 0), 2)
                roi_gray = gray[y:y+h, x:x+w]
                roi_color = frame[y:y+h, x:x+w]
                
                eyes = self.eye_cascade.detectMultiScale(roi_gray, 1.1, 3)
                
                if len(eyes) > 0:
                    is_awake = True
                    for (ex, ey, ew, eh) in eyes:
                        cv2.rectangle(roi_color, (ex, ey), (ex+ew, ey+eh), (0, 255, 0), 2)
            
            # Emit status
            self.status_ready.emit(is_awake)
            
            # Convert frame for PyQt
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qt_image)
            
            self.frame_ready.emit(pixmap)
            
            # Limit framerate slightly to reduce CPU usage
            time.sleep(0.05)
            
        cap.release()

    def stop(self):
        self.running = False
        self.wait()
