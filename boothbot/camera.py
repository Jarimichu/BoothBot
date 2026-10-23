"""Thin wrapper around an OpenCV VideoCapture for the photobooth, plus a lookup of camera names
(OpenCV only deals in device indices, which tell the operator nothing about which camera is which)."""
import ctypes
import sys
import threading
from concurrent.futures import Future

import cv2

# Matches the booth's own 30fps redraw (app.py's clock.tick). Not 60 even on cameras that can: a
# 60fps mode caps exposure at 1/60s, which on an Elgato Facecam 4K in a dim room gave a visibly
# darker image with ~3x the noise of its 30fps mode - photo quality matters more than preview
# smoothness here.
CAMERA_FPS = 30

# DirectShow COM identifiers used by list_camera_names().
_CLSID_SYSTEM_DEVICE_ENUM = "{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}"
_IID_ICREATE_DEV_ENUM = "{29840822-5B84-11D0-BD3B-00A0C911CE86}"
_CLSID_VIDEO_INPUT_DEVICE_CATEGORY = "{860BB310-5D01-11d0-BD3B-00A0C911CE86}"
_IID_IPROPERTY_BAG = "{55272A00-42CB-11CE-8135-00AA004BB851}"
_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_INPROC_SERVER = 0x1
_VT_BSTR = 8

# Vtable slots - IUnknown takes 0-2, so each interface's own methods start at 3. BindToStorage
# sits at 9 because IMoniker inherits IPersist (3) and IPersistStream (4-7) ahead of it.
_SLOT_RELEASE = 2
_SLOT_CREATE_CLASS_ENUMERATOR = 3
_SLOT_ENUM_NEXT = 3
_SLOT_BIND_TO_STORAGE = 9
_SLOT_PROPERTY_BAG_READ = 3


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, index: int = 0, width: int = None, height: int = None):
        self.index = index
        self.capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.capture.isOpened():
            raise CameraError(f"Could not open webcam at index {index}")

        if width and height:
            # Order matters on DirectShow - each set rebuilds the capture graph, and a later one
            # can silently undo an earlier one: setting FPS after MJPG drops a Logitech BRIO back to
            # uncompressed YUY2 (5fps at 1080p). FPS is pinned rather than left to each camera's
            # default mode so none can quietly pick 60fps and trade away exposure (see CAMERA_FPS).
            # MJPG last is what lets 1080p+ run at full frame rate instead of bandwidth-starved
            # uncompressed video. Cameras without MJPG (OBS/Elgato virtual cams) just keep their
            # own format. Costs a few seconds per open (~5-7s vs ~1.5s unconfigured).
            self.capture.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        # What the camera actually agreed to - a request beyond its limits gets the nearest mode
        # it has (e.g. the BRIO answers a 4K request with 1080p), not an error.
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read_frame_rgb(self, fit_within=None):
        """Returns the latest frame as an RGB numpy array, or None if the read failed. fit_within
        (width, height) scales it to fit first (see fit_frame) - for display only; captures read
        at full size."""
        ok, frame_bgr = self.capture.read()
        if not ok:
            return None
        if fit_within is not None:
            frame_bgr = fit_frame(frame_bgr, fit_within)
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    def save_frame(self, frame_rgb, path) -> bool:
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        return bool(cv2.imwrite(str(path), frame_bgr))

    def open_settings_dialog(self) -> bool:
        """Opens the camera driver's own settings window (exposure, white balance, focus, zoom...,
        whatever this camera supports). OpenCV runs it on its own thread, so this returns right
        away and the preview keeps updating behind it. Changes are applied to the camera itself."""
        return bool(self.capture.set(cv2.CAP_PROP_SETTINGS, 1))

    def release(self):
        if self.capture is not None:
            self.capture.release()


def open_camera_in_background(index, width=None, height=None) -> Future:
    """Opens a Camera on a worker thread, returning a Future for it (its result() re-raises
    CameraError). Opening at a set resolution blocks for ~5-7s - long enough for Windows to flag
    a UI thread stuck waiting on it as "Not Responding" - so callers poll done() and keep pumping
    events meanwhile. The capture is fine to use and release from the caller's thread afterward
    (checked under both Tk and pygame)."""
    future = Future()

    def run():
        try:
            future.set_result(Camera(index, width, height))
        except BaseException as exc:
            future.set_exception(exc)

    # Daemon: a camera driver that never returns mustn't keep the process alive on exit.
    threading.Thread(target=run, daemon=True).start()
    return future


def fit_frame(frame, max_size):
    """Scales a frame (any channel order) to fit max_size, keeping its aspect ratio - down or up.
    OpenCV does this several times faster than pygame's smoothscale at screen sizes: a 4K frame
    onto a 1080p screen ~3ms vs ~22ms, and a 1080p camera onto a 4K screen ~5ms vs ~18ms."""
    max_w, max_h = max_size
    height, width = frame.shape[:2]
    scale = min(max_w / width, max_h / height)
    # round(), not int(): float error can turn the limiting side's 768.0 into 767.99 -> 767, and
    # a frame 1px short of its box gets pointlessly rescaled again downstream.
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if new_size == (width, height):
        return frame
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    return cv2.resize(frame, new_size, interpolation=interpolation)


def resolve_camera_index(names, saved_index, saved_name):
    """Returns (index, found) for the saved camera. The saved name wins over the saved index,
    since indices shift whenever any camera (virtual ones included) is added or removed; found is
    False only when the saved name isn't connected, in which case the saved index is the fallback.
    names is list_camera_names()'s result (None = names unavailable, so the index is all there is)."""
    if not saved_name or names is None:
        return saved_index, True
    matches = [i for i, name in enumerate(names) if name == saved_name]
    if not matches:
        return saved_index, False
    return (saved_index if saved_index in matches else matches[0]), True


def list_camera_names():
    """Returns the name of every DirectShow video input device, where list position == the index
    Camera(index) opens: OpenCV's CAP_DSHOW backend numbers devices by walking this exact same
    enumeration. Returns [] if there are no cameras, or None if names can't be looked up at all
    (not Windows, or a COM failure) so callers can fall back to bare indices.

    Raw ctypes COM rather than pygrabber/comtypes - not worth a dependency (and comtypes' runtime
    code generation is awkward inside a PyInstaller build) for one read-only enumeration."""
    if sys.platform != "win32":
        return None
    try:
        return _enumerate_dshow_video_inputs()
    except OSError:
        return None


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _VARIANT(ctypes.Structure):
    # vt + 3 reserved words, then a union two pointers wide (16 bytes on x64, 8 on x86) - only
    # the first pointer (bstrVal) is ever read here.
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("value", ctypes.c_void_p),
        ("value_high", ctypes.c_void_p),
    ]


def _guid(ole32, text):
    guid = _GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(guid))
    return guid


def _com_method(obj, slot, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])


def _com_release(obj):
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[_SLOT_RELEASE])(obj)


def _enumerate_dshow_video_inputs():
    ole32 = ctypes.OleDLL("ole32")
    oleaut32 = ctypes.WinDLL("oleaut32")

    # A thread COM was already initialized on in another mode (RPC_E_CHANGED_MODE, raised by
    # OleDLL) can still make these calls in its existing apartment - it just mustn't be
    # uninitialized by us afterward.
    try:
        ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        com_initialized = True
    except OSError:
        com_initialized = False

    dev_enum = ctypes.c_void_p()
    enum_moniker = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance(
            ctypes.byref(_guid(ole32, _CLSID_SYSTEM_DEVICE_ENUM)),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid(ole32, _IID_ICREATE_DEV_ENUM)),
            ctypes.byref(dev_enum),
        )
        create_class_enumerator = _com_method(
            dev_enum, _SLOT_CREATE_CLASS_ENUMERATOR,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong,
        )
        create_class_enumerator(
            dev_enum, ctypes.byref(_guid(ole32, _CLSID_VIDEO_INPUT_DEVICE_CATEGORY)), ctypes.byref(enum_moniker), 0
        )
        if not enum_moniker:  # S_FALSE with no enumerator: the category is empty
            return []

        iid_property_bag = _guid(ole32, _IID_IPROPERTY_BAG)
        enum_next = _com_method(
            enum_moniker, _SLOT_ENUM_NEXT, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_ulong)
        )
        names = []
        while True:
            moniker = ctypes.c_void_p()
            fetched = ctypes.c_ulong()
            if enum_next(enum_moniker, 1, ctypes.byref(moniker), ctypes.byref(fetched)) != 0 or not fetched.value:
                break
            try:
                name = _read_friendly_name(oleaut32, moniker, iid_property_bag)
            finally:
                _com_release(moniker)
            # Every device keeps its slot even when its name can't be read - dropping one would
            # shift every later name onto the wrong OpenCV index.
            names.append(name or f"Camera {len(names)}")
        return names
    finally:
        _com_release(enum_moniker)
        _com_release(dev_enum)
        if com_initialized:
            ole32.CoUninitialize()


def _read_friendly_name(oleaut32, moniker, iid_property_bag):
    property_bag = ctypes.c_void_p()
    variant = _VARIANT()
    try:
        bind_to_storage = _com_method(
            moniker, _SLOT_BIND_TO_STORAGE,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
        )
        bind_to_storage(moniker, None, None, ctypes.byref(iid_property_bag), ctypes.byref(property_bag))
        read = _com_method(
            property_bag, _SLOT_PROPERTY_BAG_READ, ctypes.c_wchar_p, ctypes.POINTER(_VARIANT), ctypes.c_void_p
        )
        read(property_bag, "FriendlyName", ctypes.byref(variant), None)
        if variant.vt == _VT_BSTR and variant.value:
            return ctypes.wstring_at(variant.value).strip()
        return ""
    except OSError:
        return ""
    finally:
        oleaut32.VariantClear(ctypes.byref(variant))
        _com_release(property_bag)
