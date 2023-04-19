"""
Wrapper for the WinAPI of TDH (Trace Data Helper) functions:
See https://learn.microsoft.com/en-us/windows/win32/api/tdh/

Exposes two functions:

tdh_enumerate_providers:
    Returns a list of all locally registered ETW provider, each as a TdhProvider dataclass
tdh_get_provider_events:
    Given a provider GUID, returns a list of the provider's events as a list of TdhEvent dataclass
"""
import ctypes
import winerror
from enum import Enum
from functools import cache
from dataclasses import dataclass
from typing import Optional

from .common import UCHAR, USHORT, ULONG, ULONGLONG, LPVOID, sanitize_name, EztwException
from .guid import GUID


class EztwTdhException(EztwException):
    """Represents a TDH error"""


########
# WINAPI

TDH_DLL = ctypes.WinDLL("tdh.dll")

def read_wstring_at(buf, offset=0):
    if offset > len(buf):
        raise EztwTdhException("Wchar string out of bounds")
    return ctypes.wstring_at(ctypes.addressof(buf) + offset)

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ns-tdh-trace_provider_info
class TRACE_PROVIDER_INFO(ctypes.Structure):
    _fields_ = [('ProviderGuid', GUID),
                ('SchemaSource', ULONG),
                ('ProviderNameOffset', ULONG),
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ns-tdh-provider_enumeration_info
class PROVIDER_ENUMERATION_INFO(ctypes.Structure):
    _fields_ = [('NumberOfProviders', ULONG),
                ('Reserved', ULONG),
                #('TraceProviderInfoArray', LPVOID), # Ignore array pointer
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ne-tdh-decoding_source
class TDH_DECODING_SOURCE(Enum):
    DecodingSourceXMLFile = 0
    DecodingSourceWbem = 1
    DecodingSourceWPP = 2
    DecodingSourceTlg = 3
    DecodingSourceMax = 4

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/nf-tdh-tdhenumerateproviders
TdhEnumerateProviders = ctypes.WINFUNCTYPE(
    ULONG,                  # Return type
    LPVOID,                 # PPROVIDER_ENUMERATION_INFO pBuffer
    ctypes.POINTER(ULONG),  # ULONG *pBufferSize
)(("TdhEnumerateProviders", TDH_DLL))

def iterate_array_of(buf, offset, cls, array_size):
    """
    Helper function for iterating over an array of const-size structs
    """
    assert issubclass(cls, ctypes.Structure)
    # Start reading at the given offset
    cur_idx = offset
    for i in range(array_size):
        # Calculate the end offset and verify we don't overflow
        new_idx = cur_idx + ctypes.sizeof(cls)
        if new_idx > len(buf):
            raise EztwTdhException(f"Array of {cls.__name__} out of bounds")
        yield cls.from_buffer_copy(buf[cur_idx:new_idx])
        cur_idx = new_idx

# https://learn.microsoft.com/en-us/windows/win32/api/evntprov/ns-evntprov-event_descriptor
class EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [('Id', USHORT),
                ('Version', UCHAR),
                ('Channel', UCHAR),
                ('Level', UCHAR),
                ('Opcode', UCHAR),
                ('Task', USHORT),
                ('Keyword', ULONGLONG),
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ns-tdh-trace_event_info
class TRACE_EVENT_INFO(ctypes.Structure):
    _fields_ = [('ProviderGuid', GUID),
                ('EventGuid', GUID),
                ('EventDescriptor', EVENT_DESCRIPTOR),
                ('DecodingSource', ULONG),
                ('ProviderNameOffset', ULONG),
                ('LevelNameOffset', ULONG),
                ('ChannelNameOffset', ULONG),
                ('KeywordsNameOffset', ULONG),
                ('TaskNameOffset', ULONG),
                ('OpcodeNameOffset', ULONG),
                ('EventMessageOffset', ULONG),
                ('ProviderMessageOffset', ULONG),
                ('BinaryXMLOffset', ULONG),
                ('BinaryXMLSize', ULONG),
                ('EventNameOffset', ULONG),  # Can sometimes mean 'ActivityIDNameOffset'
                ('EventAttributesOffset', ULONG),  # Can sometimes mean 'RelatedActivityIDNameOffset'
                ('PropertyCount', ULONG),
                ('TopLevelPropertyCount', ULONG),
                ('Flags', ULONG),
                #('EventPropertyInfoArray', LPVOID), # Ignore array pointer
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ns-tdh-provider_event_info
class PROVIDER_EVENT_INFO(ctypes.Structure):
    _fields_ = [('NumberOfEvents', ULONG),
                ('Reserved', ULONG),
                #('EventDescriptorsArray', LPVOID), # Ignore array pointer
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ne-tdh-property_flags
class TDH_PROPERTY_FLAGS:
    PropertyStruct = 0x1
    PropertyParamLength = 0x2
    PropertyParamCount = 0x4
    PropertyWBEMXmlFragment = 0x8
    PropertyParamFixedLength = 0x10
    PropertyParamFixedCount = 0x20
    PropertyHasTags = 0x40
    PropertyHasCustomSchema = 0x80

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ns-tdh-event_property_info
class EVENT_PROPERTY_INFO_UNION(ctypes.Structure):
    _fields_ = [('InType', USHORT),
                ('OutType', USHORT),
                ('MapNameOffset', ULONG),
                ]

class EVENT_PROPERTY_INFO(ctypes.Structure):
    _fields_ = [('Flags', ULONG),
                ('NameOffset', ULONG),
                ('Union', EVENT_PROPERTY_INFO_UNION),
                ('count', USHORT),      # Can also be countPropertyIndex
                ('length', USHORT),     # Can also be lengthPropertyIndex
                ('Reserved', ULONG),    # Can also be Tags
                ]

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/ne-tdh-_tdh_in_type
class TDH_INTYPE(Enum):
    INTYPE_NULL = 0
    INTYPE_UNICODESTRING = 1
    INTYPE_ANSISTRING = 2
    INTYPE_INT8 = 3
    INTYPE_UINT8 = 4
    INTYPE_INT16 = 5
    INTYPE_UINT16 = 6
    INTYPE_INT32 = 7
    INTYPE_UINT32 = 8
    INTYPE_INT64 = 9
    INTYPE_UINT64 = 10
    INTYPE_FLOAT = 11
    INTYPE_DOUBLE = 12
    INTYPE_BOOLEAN = 13
    INTYPE_BINARY = 14
    INTYPE_GUID = 15
    INTYPE_POINTER = 16
    INTYPE_FILETIME = 17
    INTYPE_SYSTEMTIME = 18
    INTYPE_SID = 19
    INTYPE_HEXINT32 = 20
    INTYPE_HEXINT64 = 21
    INTYPE_MANIFEST_COUNTEDSTRING = 22
    INTYPE_MANIFEST_COUNTEDANSISTRING = 23
    INTYPE_RESERVED24 = 24
    INTYPE_MANIFEST_COUNTEDBINARY = 25
    INTYPE_COUNTEDSTRING = 26
    INTYPE_COUNTEDANSISTRING = 27
    INTYPE_REVERSEDCOUNTEDSTRING = 28
    INTYPE_REVERSEDCOUNTEDANSISTRING = 29
    INTYPE_NONNULLTERMINATEDSTRING = 30
    INTYPE_NONNULLTERMINATEDANSISTRING = 31
    INTYPE_UNICODECHAR = 32
    INTYPE_ANSICHAR = 33
    INTYPE_SIZET = 34
    INTYPE_HEXDUMP = 35
    INTYPE_WBEMSID = 36

# For those sneaky undocumented ones
TDH_INTYPE_MAX_VALUE = max([x.value for x in TDH_INTYPE.__members__.values()])

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/nf-tdh-tdhenumeratemanifestproviderevents
TdhEnumerateManifestProviderEvents = ctypes.WINFUNCTYPE(
    ULONG,                  # Return value
    ctypes.POINTER(GUID),   # LPGUID ProviderGuid
    LPVOID,                 # PPROVIDER_EVENT_INFO Buffer
    ctypes.POINTER(ULONG),  # ULONG *BufferSize
)(("TdhEnumerateManifestProviderEvents", TDH_DLL))

# https://learn.microsoft.com/en-us/windows/win32/api/tdh/nf-tdh-tdhgetmanifesteventinformation
TdhGetManifestEventInformation = ctypes.WINFUNCTYPE(
    ULONG,                              # Return value
    ctypes.POINTER(GUID),               # LPGUID ProviderGuid
    ctypes.POINTER(EVENT_DESCRIPTOR),   # PEVENT_DESCRIPTOR EventDescriptor
    LPVOID,                             # PTRACE_EVENT_INFO Buffer
    ctypes.POINTER(ULONG),              # ULONG *BufferSize
)(("TdhGetManifestEventInformation", TDH_DLL))


########
# Eztw

@dataclass
class TdhProvider:
    """
    Represents the metadata of a single provider - guid, name and "decoding source" (usually XML schema)
    """
    guid: str
    name: str
    schema: TDH_DECODING_SOURCE

@cache
def tdh_enumerate_providers() -> list[TdhProvider]:
    """
    Invokes TdhEnumerateProviders to get a list of provider metadata. Results are cached.

    @return: list of TdhProvider instances
    """
    # Call TdhEnumerateProviders with NULL to get the required size (Microsoft-style...)
    size = ULONG(0)
    rc = TdhEnumerateProviders(0, ctypes.byref(size))
    if rc != winerror.ERROR_INSUFFICIENT_BUFFER:
        raise EztwTdhException(f"TdhEnumerateProviders failed with error {rc}")
    # Call TdhEnumerateProviders again with allocated buffer
    buf = ctypes.create_string_buffer(size.value)
    rc = TdhEnumerateProviders(ctypes.byref(buf), ctypes.byref(size))
    if rc != winerror.ERROR_SUCCESS:
        raise EztwTdhException(f"TdhEnumerateProviders failed with error {rc}")
    # Parse the PROVIDER_ENUMERATION_INFO struct
    pei = PROVIDER_ENUMERATION_INFO.from_buffer_copy(buf[:ctypes.sizeof(PROVIDER_ENUMERATION_INFO)])
    # Get providers info from the array
    providers = []
    # Iterate an array of TRACE_PROVIDER_INFO structs
    for trace_provider_info in iterate_array_of(
            buf, ctypes.sizeof(PROVIDER_ENUMERATION_INFO), TRACE_PROVIDER_INFO, pei.NumberOfProviders):
        schema_source = TDH_DECODING_SOURCE(trace_provider_info.SchemaSource)
        # Add new TdhProvider
        providers.append(TdhProvider(
            str(trace_provider_info.ProviderGuid),
            read_wstring_at(buf, trace_provider_info.ProviderNameOffset),
            schema_source))
    return providers

@dataclass
class TdhEventField:
    """
    Represents a single event's field - name, type and optional length/count fields
    """
    name: str
    type: TDH_INTYPE
    length: Optional[str] = None  # Either the name of the field that holds the byte size of this field, or None
    count: Optional[str] = None   # Either the name of the field that holds the count of this fild, or None

@dataclass
class TdhEvent:
    """
    Represents a single event - provider GUID, ID, version, name (optional), keyword and a list of TdhEventField
    """
    provider_guid: str
    id: int
    version: int
    name: str
    keyword: int
    fields: list[TdhEventField]

@cache
def tdh_get_provider_events(provider_guid: str) -> list[TdhEvent]:
    """
    Given a provider's GUID attempts to return a list of TdhEvent for this provider using the TDH API.
    Note that each version of each event is represented as an independent TdhEvent.
    May raise EztwTdhException if the provider's event info cannot be retrieved using the TDH API.

    @param provider_guid: a valid GUID string
    @return: list of TdhEvent
    """
    # Convert the GUID string to a GUID struct
    provider_guid_struct = GUID(provider_guid)
    # Call TdhEnumerateManifestProviderEvents with NULL to get the required size (Microsoft-style...)
    size = ULONG(0)
    rc = TdhEnumerateManifestProviderEvents(ctypes.byref(provider_guid_struct), 0, ctypes.byref(size))
    if rc != winerror.ERROR_INSUFFICIENT_BUFFER:
        raise EztwTdhException(
            f"TdhEnumerateManifestProviderEvents failed for provider {provider_guid} with error {rc}")
    # Call TdhEnumerateManifestProviderEvents again with allocated buffer
    buf = ctypes.create_string_buffer(size.value)
    rc = TdhEnumerateManifestProviderEvents(ctypes.byref(provider_guid_struct), buf, ctypes.byref(size))
    if rc != winerror.ERROR_SUCCESS:
        raise EztwTdhException(
            f"TdhEnumerateManifestProviderEvents failed for provider {provider_guid} with error {rc}")
    # Parse the PROVIDER_EVENT_INFO struct
    pei = PROVIDER_EVENT_INFO.from_buffer_copy(buf[:ctypes.sizeof(PROVIDER_EVENT_INFO)])
    # Enumerate array of EVENT_DESCRIPTOR
    events = []
    for event_descriptor in iterate_array_of(
            buf, ctypes.sizeof(PROVIDER_EVENT_INFO), EVENT_DESCRIPTOR, pei.NumberOfEvents):
        # Call TdhGetManifestEventInformation with NULL to get the required size (Microsoft-style...)
        event_info_size = ULONG(0)
        rc = TdhGetManifestEventInformation(
            ctypes.byref(provider_guid_struct), ctypes.byref(event_descriptor), 0, ctypes.byref(event_info_size))
        if rc != winerror.ERROR_INSUFFICIENT_BUFFER:
            raise EztwTdhException(
                f"TdhGetManifestEventInformation failed for provider {provider_guid} with error {rc}")
        # Call TdhGetManifestEventInformation again with allocated buffer
        event_info_buf = ctypes.create_string_buffer(event_info_size.value)
        rc = TdhGetManifestEventInformation(
            ctypes.byref(provider_guid_struct), ctypes.byref(event_descriptor),
            event_info_buf, ctypes.byref(event_info_size))
        if rc != winerror.ERROR_SUCCESS:
            raise EztwTdhException(
                f"TdhGetManifestEventInformation failed for provider {provider_guid} with error {rc}")
        # Parse the TRACE_EVENT_INFO struct
        trace_event_info = TRACE_EVENT_INFO.from_buffer_copy(event_info_buf)
        # Event ID/version uniquely identify this event in this provider
        event_id = trace_event_info.EventDescriptor.Id
        event_version = trace_event_info.EventDescriptor.Version
        # Event keyword control the consumed events
        # https://learn.microsoft.com/en-us/windows/win32/api/evntprov/ns-evntprov-event_descriptor
        event_keyword = trace_event_info.EventDescriptor.Keyword & 0x0000FFFFFFFFFFFF
        # Take either the event name or task name
        event_name = None
        if trace_event_info.EventNameOffset > 0:
            event_name = read_wstring_at(event_info_buf, trace_event_info.EventNameOffset).rstrip(' ')
        elif trace_event_info.TaskNameOffset > 0:
            event_name = read_wstring_at(event_info_buf, trace_event_info.TaskNameOffset).rstrip(' ')
        # Iterate over event properties array
        # https://learn.microsoft.com/en-us/windows/win32/etw/retrieving-event-metadata
        fields = []
        for event_property_info in iterate_array_of(
                event_info_buf, ctypes.sizeof(TRACE_EVENT_INFO),
                EVENT_PROPERTY_INFO, trace_event_info.TopLevelPropertyCount):
            # Get the field name
            field_name = sanitize_name(read_wstring_at(event_info_buf, event_property_info.NameOffset))
            length_field = None
            # If this is a fixed-length field - keep the int value
            if event_property_info.Flags & TDH_PROPERTY_FLAGS.PropertyParamFixedLength:
                length_field = event_property_info.length
            # Else if this field's length in bytes is described in another field, record it
            elif event_property_info.Flags & TDH_PROPERTY_FLAGS.PropertyParamLength:
                length_index = event_property_info.length
                if length_index > len(fields):
                    raise EztwTdhException(
                        f"Provider {provider_guid} - {event_name} length field index too high")
                length_field = fields[length_index].name
            count_field = None
            # If this is a fixed-count field - keep the int value
            if event_property_info.Flags & TDH_PROPERTY_FLAGS.PropertyParamFixedCount:
                count_field = event_property_info.count
            # Else if this field's count (repeated array) is described in another field, record it
            elif event_property_info.Flags & TDH_PROPERTY_FLAGS.PropertyParamCount:
                count_index = event_property_info.count
                if count_index > len(fields):
                    raise EztwTdhException(
                        f"Provider {provider_guid} - {event_name} count field index too high")
                count_field = fields[count_index].name
            # TODO: check other (currently unsupported) flags?
            assert count_field is None or length_field is None # They can't be both used at the same time...
            # Field type ("intype") - if unknown, keep the integer value
            intype_value = event_property_info.Union.InType
            if intype_value <= TDH_INTYPE_MAX_VALUE:
                intype_value = TDH_INTYPE(intype_value)
            # Append field
            fields.append(TdhEventField(field_name, intype_value, length_field, count_field))
        # Append event
        events.append(TdhEvent(provider_guid, event_id, event_version, event_name, event_keyword, fields))
    return events
