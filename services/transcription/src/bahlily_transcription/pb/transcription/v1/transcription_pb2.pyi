from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Engine(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ENGINE_UNSPECIFIED: _ClassVar[Engine]
    ENGINE_WHISPER: _ClassVar[Engine]
    ENGINE_PARAKEET: _ClassVar[Engine]

ENGINE_UNSPECIFIED: Engine
ENGINE_WHISPER: Engine
ENGINE_PARAKEET: Engine

class TranscriptSegment(_message.Message):
    __slots__ = (
        "text",
        "segment_id",
        "confidence",
        "is_partial",
        "engine",
        "model_name",
        "audio_start_time",
        "audio_end_time",
        "language",
        "recording_id",
        "trace_id",
    )
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SEGMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    IS_PARTIAL_FIELD_NUMBER: _ClassVar[int]
    ENGINE_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    AUDIO_START_TIME_FIELD_NUMBER: _ClassVar[int]
    AUDIO_END_TIME_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    RECORDING_ID_FIELD_NUMBER: _ClassVar[int]
    TRACE_ID_FIELD_NUMBER: _ClassVar[int]
    text: str
    segment_id: int
    confidence: float
    is_partial: bool
    engine: Engine
    model_name: str
    audio_start_time: float
    audio_end_time: float
    language: str
    recording_id: str
    trace_id: str
    def __init__(
        self,
        text: _Optional[str] = ...,
        segment_id: _Optional[int] = ...,
        confidence: _Optional[float] = ...,
        is_partial: _Optional[bool] = ...,
        engine: _Optional[_Union[Engine, str]] = ...,
        model_name: _Optional[str] = ...,
        audio_start_time: _Optional[float] = ...,
        audio_end_time: _Optional[float] = ...,
        language: _Optional[str] = ...,
        recording_id: _Optional[str] = ...,
        trace_id: _Optional[str] = ...,
    ) -> None: ...

class StreamTranscriptsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StreamTranscriptsResponse(_message.Message):
    __slots__ = ("segment",)
    SEGMENT_FIELD_NUMBER: _ClassVar[int]
    segment: TranscriptSegment
    def __init__(self, segment: _Optional[_Union[TranscriptSegment, _Mapping]] = ...) -> None: ...
