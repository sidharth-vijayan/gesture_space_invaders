"""
cv_controller.py
Handles webcam input using MediaPipe Hands and converts it into normalized controls.

Exposes:
- CVController.start(): spawns background thread reading frames
- CVController.get_controls(): returns (x_norm [0..1] or None, shoot_bool, confidence, bgr_preview_image)
- tuning constants: DEADZONE, SMOOTHING_ALPHA, PINCH_THRESHOLD, MIN_CONFIDENCE

Designed to be CPU-friendly. If MediaPipe not available or no camera, falls back to static controls.
"""
import threading
import time
import cv2
import mediapipe as mp
import numpy as np

# Tuning constants
DEADZONE = 0.03          # Ignore small movements
SMOOTHING_ALPHA = 0.35   # Lower = smoother, higher = more responsive
PINCH_THRESHOLD = 0.06   # Thumb-index distance to trigger shoot
MIN_CONFIDENCE = 0.5

class CVController:
    def __init__(self, camera_index=0):
        self.cam_idx = camera_index
        self.cap = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # Outputs
        self._x_norm = None
        self._shoot = False
        self._confidence = 0.0
        self._preview = None
        self._prev_x = None

        # MediaPipe
        self.mp_hands = mp.solutions.hands
        self.hands = None

    # Helpers
    @staticmethod
    def smooth_pos(prev, new, alpha=SMOOTHING_ALPHA):
        if prev is None:
            return new
        return prev * (1 - alpha) + new * alpha

    @staticmethod
    def in_deadzone(center, value, dz=DEADZONE):
        return abs(value - center) < dz

    def start(self):
        if self._running:
            return

        self.cap = cv2.VideoCapture(self.cam_idx)
        if not self.cap.isOpened():
            print("WARNING: Couldn't open camera. CV disabled.")
            return

        # Reduce CPU load
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.4,
            min_tracking_confidence=0.4
        )

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
        if self.hands:
            self.hands.close()

    def _run(self):
        drawing = mp.solutions.drawing_utils
        connections = self.mp_hands.HAND_CONNECTIONS

        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.02)
                continue

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.hands.process(rgb)

            x_norm = None
            shoot = False
            conf = 0.0
            preview = frame.copy()

            if results.multi_hand_landmarks:
                hand = results.multi_hand_landmarks[0]

                # Use middle finger MCP (landmark 9) as X reference
                lx = hand.landmark[9].x
                x_norm = max(0.0, min(1.0, lx))

                # Detect pinch (thumb tip 4, index tip 8)
                thumb = hand.landmark[4]
                index = hand.landmark[8]
                d = np.hypot(thumb.x - index.x, thumb.y - index.y)

                conf = 1.0
                shoot = (d < PINCH_THRESHOLD and conf > MIN_CONFIDENCE)

                # Draw landmarks
                drawing.draw_landmarks(preview, hand, connections)

            # Apply smoothing + deadzone
            with self._lock:
                if x_norm is not None:
                    if self._prev_x is None:
                        self._prev_x = x_norm

                    if not self.in_deadzone(self._prev_x, x_norm):
                        self._prev_x = self.smooth_pos(self._prev_x, x_norm)

                    self._x_norm = float(self._prev_x)
                else:
                    self._x_norm = None

                self._shoot = shoot
                self._confidence = conf
                self._preview = preview

            time.sleep(0.01)

    def get_controls(self):
        with self._lock:
            return self._x_norm, self._shoot, self._confidence, self._preview


if __name__ == "__main__":
    c = CVController()
    c.start()
    try:
        while True:
            print(c.get_controls())
            time.sleep(0.2)
    except KeyboardInterrupt:
        c.stop()
