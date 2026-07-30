from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DeviceType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DEVICE_TYPE_UNSPECIFIED: _ClassVar[DeviceType]
    DEVICE_TYPE_MICROPHONE: _ClassVar[DeviceType]
    DEVICE_TYPE_SYSTEM: _ClassVar[DeviceType]
DEVICE_TYPE_UNSPECIFIED: DeviceType
DEVICE_TYPE_MICROPHONE: DeviceType
DEVICE_TYPE_SYSTEM: DeviceType

class AudioSegment(_message.Message):
    __slots__ = ("data", "sample_rate", "timestamp", "segment_id", "device_type", "trace_id")
    DATA_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_TYPE_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    data: _containers.RepeatedScalarFieldContainer[float]
    sample_rate: int
    timestamp: float
    segment_id: int
    device_type: DeviceType
    trace_id: str
    def __init__(self, data: _Optional[_Iterable[float]] = ..., sample_rate: _Optional[int] = ..., timestamp: _Optional[float] = ..., segment_id: _Optional[int] = ..., device_type: _Optional[_Union[DeviceType, str]] = ..., trace_id: _Optional[str] = ...) -> None: ...

class StreamAudioRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StreamAudioResponse(_message.Message):
    __slots__ = ("segment",)
    SEGMENT_FIELD_NUMBER: _ClassVar[int]
    segment: AudioSegment
    def __init__(self, segment: _Optional[_Union[AudioSegment, _Mapping]] = ...) -> None: ...
