"""Thin wrapper around an OpenCV VideoCapture for the photobooth, plus a lookup of camera names
(OpenCV only deals in device indices, which tell the operator nothing about which camera is which)."""
import ctypes
import sys

import cv2

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
