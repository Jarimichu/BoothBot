"""Thin wrapper around an OpenCV VideoCapture for the photobooth."""
import cv2


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, index: int = 0):
        self.index = index
        self.capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.capture.isOpened():
            raise CameraError(f"Could not open webcam at index {index}")

    def read_frame_rgb(self):
        """Returns the latest frame as an RGB numpy array, or None if the read failed."""
        ok, frame_bgr = self.capture.read()
        if not ok:
            return None
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    def save_frame(self, frame_rgb, path) -> bool:
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        return bool(cv2.imwrite(str(path), frame_bgr))

    def release(self):
        if self.capture is not None:
            self.capture.release()
