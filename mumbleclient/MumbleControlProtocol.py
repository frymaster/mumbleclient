import twisted.protocols.stateful

import Mumble_pb2

import sys
import struct

_MESSAGE_HEADER=">HI"

_MESSAGE_TYPES= [
    "Version",
    "UDPTunnel",
    "Authenticate",
    "Ping",
    "Reject",
    "ServerSync",
    "ChannelRemove",
    "ChannelState",
    "UserRemove",
    "UserState",
    "BanList",
    "TextMessage",
    "PermissionDenied",
    "ACL",
    "QueryUsers",
    "CryptSetup",
    "ContextActionModify",
    "ContextAction",
    "UserList",
    "VoiceTarget",
    "PermissionQuery",
    "CodecVersion",
    "UserStats",
    "RequestBlob",
    "ServerConfig",
    "SuggestConfig"
]

_MESSAGE_LOOKUP_BY_OBJECT={}
_MESSAGE_LOOKUP_BY_NUMBER={}

def getMessageObject(messageId):
    return _MESSAGE_LOOKUP_BY_NUMBER[messageId]()

def getMessageId(messageObject):
    return _MESSAGE_LOOKUP_BY_OBJECT[type(messageObject)]

def getMessageName(id):
    return _MESSAGE_TYPES[id]

def _addMessageObjectsToModule():
    module = sys.modules[__name__]
    for i in range(len(_MESSAGE_TYPES)):
        message = getattr(Mumble_pb2,_MESSAGE_TYPES[i])
        _MESSAGE_LOOKUP_BY_OBJECT[message]=i
        _MESSAGE_LOOKUP_BY_NUMBER[i]=message
        setattr(module,_MESSAGE_TYPES[i],message)

class MumbleControlProtocol(twisted.protocols.stateful.StatefulProtocol):

    def __init__(self,client):
        self.client=client
        client.controlProtocol=self

    def getInitialState(self):
        return (self.messageHeaderReceived,6)

    def messageHeaderReceived(self,data):
        msgType,length=struct.unpack(_MESSAGE_HEADER,data)
        self._msgType = msgType
        return (self.messageBodyReceived,length)

    def messageBodyReceived(self,data):
        if self._msgType < len(_MESSAGE_TYPES):
            if self._msgType ==1:
                self.client._TCPVoiceMessageReceived(data)
            else:
                message=getMessageObject(self._msgType)
                message.ParseFromString(data)
                self.client._controlMessageReceived(self._msgType,_MESSAGE_TYPES[self._msgType],message)
        else:
            self.client._unknownMessageReceived(self._msgType,data)
        return (self.messageHeaderReceived,6)

    def sendMessage(self,messageObject):
        id = getMessageId(messageObject)
        bytesMessage = messageObject.SerializeToString()
        length = len(bytesMessage)
        message = struct.pack(_MESSAGE_HEADER,id,length)+bytesMessage
        self.transport.write(message)

    def sendVoiceMessage(self,bytesMessage):
        length = len(bytesMessage)
        message = struct.pack(_MESSAGE_HEADER,1,length)+bytesMessage
        self.transport.write(message)

    def connectionMade(self):
        self.client._connectionMade()

    def connectionLost(self,reason):
        self.client._connectionLost(reason)

    def disconnect(self):
        self.transport.loseConnection()

_addMessageObjectsToModule()
